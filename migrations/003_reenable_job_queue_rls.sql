-- Migration 003: Re-enable RLS on job_queue
--
-- Migration 002 disabled RLS on job_queue after an old supabase-py version appeared
-- not to bypass RLS on INSERT via the service-role key. That reasoning missed that
-- disabling RLS doesn't just stop blocking the backend — the service-role key always
-- bypasses RLS at the Postgres level regardless of policies — it also opens the table
-- to the public internet: anyone holding the anon key (shipped to every browser) could
-- read or write every user's queue entries directly via Supabase's REST API.
--
-- Re-enabled 2026-09-02 as part of a production-readiness audit. Verified live: a real
-- job enqueue -> process -> fail cycle completed successfully afterward, confirming
-- the current supabase-py version's service-role client still bypasses RLS correctly.
-- Applied directly to the live database via the Supabase MCP — this file exists for
-- history/parity with 001/002, matching the actual migration file added to the
-- frontend repo (video-generator-fe/supabase/migrations/20260902010000_...).

ALTER TABLE job_queue ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read own jobs"
  ON job_queue FOR SELECT
  USING (auth.uid() = user_id);
