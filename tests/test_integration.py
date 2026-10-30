"""PostgreSQL integration checks for dispatch, isolation, concurrent claims and stale workers."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from bot_core import store
from bot_core.config import settings
from event_receiver.main import handle


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    """Use an explicitly configured disposable database, never a production database."""
    if os.environ.get("BOT_TEST_DATABASE") != "1":
        pytest.skip("Set BOT_TEST_DATABASE=1 and DATABASE_URL for disposable integration DB")
    config = {"bots": [{"code": "a", "app_id": "app-a", "tenant_key": "tenant-a",
                        "open_id": "bot-a", "allowed_chats": ["chat-a"]}],
              "clients": [{"employee_code": "alice", "token_env": "TEST_TOKEN", "bots": ["a"]}]}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("BOT_CONFIG", str(path))
    monkeypatch.setenv("TEST_TOKEN", "x" * 40)
    settings.cache_clear()
    with store.connect() as conn:
        conn.execute("TRUNCATE ve_bot_task_audit,ve_bot_task,ve_bot_event RESTART IDENTITY CASCADE")
    yield
    settings.cache_clear()


def event():
    """Build a synthetic group mention without real company content."""
    return {"header": {"app_id": "app-a", "tenant_key": "tenant-a", "event_id": "evt-1",
                       "event_type": "im.message.receive_v1"},
            "event": {"message": {"chat_id": "chat-a", "message_type": "text",
                      "mentions": [{"id": {"open_id": "bot-a"}}],
                      "content": json.dumps({"text": "@bot Check https://example.feishu.cn/wiki/abc"})}}}


def test_dispatch_deduplicates_and_filters():
    """Repeated delivery creates exactly one task; unrelated chats are ignored."""
    payload = event()
    assert handle("a", payload)
    assert not handle("a", payload)
    payload["event"]["message"]["chat_id"] = "other"
    assert not handle("a", payload)
    assert len(store.list_tasks(["a"])) == 1
    assert store.list_tasks(["b"]) == []


def test_concurrent_claim_and_lease_fence():
    """Only one worker claims a task; expired fences cannot submit after re-claim."""
    handle("a", event())
    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda employee: store.claim(["a"], employee), ["alice", "bob"]))
    task = next(task for task in claims if task)
    assert sum(task is not None for task in claims) == 1
    with pytest.raises(ValueError):
        store.transition(["b"], task["claimed_by"], task["code"], task["lease_token"], "complete", "wrong scope")
    store.transition(["a"], task["claimed_by"], task["code"], task["lease_token"], "renew")
    with store.connect() as conn:
        conn.execute("UPDATE ve_bot_task SET lease_until=now()-interval '1 second'")
    replacement = store.claim(["a"], "carol")
    assert replacement["lease_token"] != task["lease_token"]
    with pytest.raises(ValueError):
        store.transition(["a"], task["claimed_by"], task["code"], task["lease_token"], "complete", "stale")
    store.transition(["a"], "carol", replacement["code"], replacement["lease_token"], "complete", "Analysis only")
    assert store.context(["a"], "carol", task["code"])["result"] == "Analysis only"


def test_identity_and_mentions():
    """Forged app identity fails; missing bot mentions do not enqueue."""
    payload = event()
    payload["header"]["app_id"] = "other"
    with pytest.raises(ValueError):
        handle("a", payload)
    payload = event()
    payload["event"]["message"]["mentions"] = []
    assert not handle("a", payload)


def test_release_and_employee_fence():
    """Another employee cannot submit a claimed task; release makes work claimable."""
    handle("a", event())
    task = store.claim(["a"], "alice")
    with pytest.raises(ValueError):
        store.transition(["a"], "bob", task["code"], task["lease_token"], "complete", "not mine")
    store.transition(["a"], "alice", task["code"], task["lease_token"], "release")
    assert store.claim(["a"], "bob")["attempts"] == 2
