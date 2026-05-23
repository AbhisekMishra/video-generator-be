-- Migration 001: Job queue for rate limiting and request queuing
-- Run this in your Supabase SQL editor before deploying the new backend.

-- 1. Create the job_queue table
CREATE TABLE IF NOT EXISTS job_queue (
  id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  session_id     TEXT        NOT NULL,
  payload        JSONB       NOT NULL DEFAULT '{}',
  status         TEXT        NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')),
  queue_position INTEGER,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  started_at     TIMESTAMPTZ,
  completed_at   TIMESTAMPTZ,
  error          TEXT
);

-- 2. Indexes for fast worker polling (oldest pending first, user active-job check)
CREATE INDEX IF NOT EXISTS idx_job_queue_status_created
  ON job_queue (status, created_at);

CREATE INDEX IF NOT EXISTS idx_job_queue_user_status
  ON job_queue (user_id, status);

-- 3. RLS: users can read their own queue entries (backend uses service-role key to write)
ALTER TABLE job_queue ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read own jobs"
  ON job_queue FOR SELECT
  USING (auth.uid() = user_id);

-- 4. Add 'queued' to the sessions status constraint (safe no-op if constraint doesn't exist)
DO $$
BEGIN
  ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_status_check;
  ALTER TABLE sessions
    ADD CONSTRAINT sessions_status_check
    CHECK (status IN ('pending', 'queued', 'processing', 'completed', 'failed'));
EXCEPTION WHEN OTHERS THEN
  NULL;
END $$;
