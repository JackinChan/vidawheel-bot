-- Durable inbox and leased tasks; app identities and employees use codes.
CREATE TABLE IF NOT EXISTS ve_bot_event (
    id bigserial PRIMARY KEY,
    code varchar(60) NOT NULL UNIQUE,
    bot_code varchar(60) NOT NULL,
    event_id text NOT NULL,
    payload jsonb NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(bot_code, event_id)
);
CREATE TABLE IF NOT EXISTS ve_bot_task (
    id bigserial PRIMARY KEY,
    code varchar(60) NOT NULL UNIQUE,
    bot_code varchar(60) NOT NULL,
    event_code varchar(60) NOT NULL UNIQUE REFERENCES ve_bot_event(code),
    question text NOT NULL,
    document_url text,
    status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','running','completed','failed')),
    claimed_by varchar(60),
    lease_token uuid,
    lease_until timestamptz,
    attempts integer NOT NULL DEFAULT 0,
    result text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ve_bot_task_queue_idx ON ve_bot_task(bot_code,status,created_at);
CREATE TABLE IF NOT EXISTS ve_bot_task_audit (
    id bigserial PRIMARY KEY,
    code varchar(60) NOT NULL UNIQUE,
    task_code varchar(60) NOT NULL REFERENCES ve_bot_task(code),
    employee_code varchar(60) NOT NULL,
    action text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
-- Correlated issue revisions, retry scheduling and immutable analysis history.
ALTER TABLE ve_bot_task ADD COLUMN IF NOT EXISTS thread_key text;
UPDATE ve_bot_task SET thread_key=event_code WHERE thread_key IS NULL;
ALTER TABLE ve_bot_task ALTER COLUMN thread_key SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ve_bot_task_thread_idx ON ve_bot_task(bot_code,thread_key);
ALTER TABLE ve_bot_task ADD COLUMN IF NOT EXISTS revision integer NOT NULL DEFAULT 1;
ALTER TABLE ve_bot_task ADD COLUMN IF NOT EXISTS claimed_revision integer;
ALTER TABLE ve_bot_task ADD COLUMN IF NOT EXISTS next_attempt_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE ve_bot_task ADD COLUMN IF NOT EXISTS last_error text;
CREATE TABLE IF NOT EXISTS ve_bot_task_event (
    id bigserial PRIMARY KEY,
    code varchar(60) NOT NULL UNIQUE,
    task_code varchar(60) NOT NULL REFERENCES ve_bot_task(code),
    event_code varchar(60) NOT NULL UNIQUE REFERENCES ve_bot_event(code)
);
INSERT INTO ve_bot_task_event(code,task_code,event_code)
SELECT t.code,t.code,t.event_code FROM ve_bot_task t ON CONFLICT(event_code) DO NOTHING;
CREATE TABLE IF NOT EXISTS ve_bot_analysis (
    id bigserial PRIMARY KEY,
    code varchar(60) NOT NULL UNIQUE,
    task_code varchar(60) NOT NULL REFERENCES ve_bot_task(code),
    employee_code varchar(60) NOT NULL,
    revision integer NOT NULL,
    result text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
-- Preserve the exact text/comment revision used by each analysis, excluding image bytes.
ALTER TABLE ve_bot_task ADD COLUMN IF NOT EXISTS context_snapshot jsonb;
ALTER TABLE ve_bot_analysis ADD COLUMN IF NOT EXISTS context_snapshot jsonb;
