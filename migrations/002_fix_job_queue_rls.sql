-- Migration 002: Disable RLS on job_queue
--
-- job_queue is a server-side-only table — only the backend (service-role key)
-- reads and writes it. Enabling RLS with only a SELECT policy blocked INSERT
-- because some Supabase Python client versions don't send the service-role
-- bypass header on all request types.
--
-- Users never query this table directly; they get queue position through
-- the /api/queue-position/{sessionId} Next.js route, which calls the
-- FastAPI backend. RLS on this table provides no security benefit.

ALTER TABLE job_queue DISABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can read own jobs" ON job_queue;
