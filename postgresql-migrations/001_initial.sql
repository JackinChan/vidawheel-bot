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
