"""PostgreSQL inbox, atomic task claims and fenced lease operations."""
import json
import os
from uuid import uuid4
from datetime import datetime

import psycopg
from psycopg.rows import dict_row


def connect():
    """Open a short-lived connection; callers own the transaction boundary."""
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=10)


def serial(row):
    """Normalize database values to MCP JSON with ISO-8601 UTC timestamps."""
    if row is None:
        return None
    return {key: value.isoformat().replace("+00:00", "Z") if isinstance(value, datetime)
            else str(value) if key == "lease_token" and value else value for key, value in row.items()}


def ingest(bot: str, event_id: str, payload: dict, question: str, document_url: str | None):
    """Commit event and task atomically; repeated delivery creates no extra task."""
    with connect() as conn:
        code = str(uuid4())
        row = conn.execute("""INSERT INTO ve_bot_event(code,bot_code,event_id,payload)
            VALUES(%s,%s,%s,%s::jsonb) ON CONFLICT(bot_code,event_id) DO NOTHING RETURNING code""",
            (code, bot, event_id, json.dumps(payload))).fetchone()
        if row:
            conn.execute("""INSERT INTO ve_bot_task(code,bot_code,event_code,question,document_url)
                VALUES(%s,%s,%s,%s,%s)""", (str(uuid4()), bot, code, question, document_url))
        return bool(row)


def list_tasks(bots: list[str], limit: int = 20):
    """List permitted task summaries; omit results and lease secrets."""
    with connect() as conn:
        rows = conn.execute("""SELECT code,bot_code,status,question,document_url,created_at
            FROM ve_bot_task WHERE bot_code=ANY(%s) ORDER BY created_at DESC LIMIT %s""",
            (bots, max(1, min(limit, 100)))).fetchall()
        return [serial(row) for row in rows]


def claim(bots: list[str], employee: str):
    """Atomically claim one pending or expired task using SKIP LOCKED and a new fence."""
    with connect() as conn:
        row = conn.execute("""WITH candidate AS (
            SELECT id FROM ve_bot_task WHERE bot_code=ANY(%s)
            AND (status='pending' OR (status='running' AND lease_until < now()))
            ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
            UPDATE ve_bot_task t SET status='running',claimed_by=%s,lease_token=%s,
            lease_until=now()+interval '5 minutes',attempts=attempts+1,updated_at=now()
            FROM candidate c WHERE t.id=c.id RETURNING t.*""", (bots, employee, uuid4())).fetchone()
        if row:
            audit(conn, row["code"], employee, "claim")
        return serial(row)


def audit(conn, code: str, employee: str, action: str):
    """Record an attributable task transition in the same transaction."""
    conn.execute("INSERT INTO ve_bot_task_audit(code,task_code,employee_code,action) VALUES(%s,%s,%s,%s)",
                 (str(uuid4()), code, employee, action))


def transition(bots, employee, code, fence, action, result=None):
    """Renew, release or complete only a current, unexpired, employee-owned lease."""
    updates = {
        "renew": "lease_until=now()+interval '5 minutes'",
        "release": "status='pending',claimed_by=NULL,lease_token=NULL,lease_until=NULL",
        "complete": "status='completed',result=%s,lease_until=NULL,lease_token=NULL",
    }
    if action not in updates:
        raise ValueError("Unknown transition")
    args = [result] if action == "complete" else []
    args += [code, bots, employee, fence]
    with connect() as conn:
        row = conn.execute("UPDATE ve_bot_task SET " + updates[action] + """,updated_at=now()
            WHERE code=%s AND bot_code=ANY(%s) AND claimed_by=%s AND lease_token=%s::uuid
            AND status='running' AND lease_until > now() RETURNING code,status,lease_until""", args).fetchone()
        if not row:
            raise ValueError("Task unavailable or lease expired")
        audit(conn, code, employee, action)
        return serial(row)


def context(bots, employee, code):
    """Read a task only within authorized bot scope; omit another worker's fence."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM ve_bot_task WHERE code=%s AND bot_code=ANY(%s)", (code, bots)).fetchone()
        if not row:
            raise ValueError("Task unavailable")
        row.pop("lease_token", None)
        return serial(row)
