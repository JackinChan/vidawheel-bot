-- Preserve the exact text/comment revision used by each analysis, excluding image bytes.
ALTER TABLE ve_bot_task ADD COLUMN IF NOT EXISTS context_snapshot jsonb;
ALTER TABLE ve_bot_analysis ADD COLUMN IF NOT EXISTS context_snapshot jsonb;
