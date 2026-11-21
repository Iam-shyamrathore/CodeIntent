-- Runs: every pull request check, repository scan and MCP call, one row per attempt, with timed steps.
-- result: the full outcome (verdicts, scan items or the MCP tool's structured result).
CREATE TABLE IF NOT EXISTS ci_runs(
  id uuid PRIMARY KEY,
  installation_id bigint REFERENCES ci_installations(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK(kind IN ('pull','scan','mcp')),
  repository text,
  ref text,
  subject text NOT NULL,
  status text NOT NULL DEFAULT 'running' CHECK(status IN ('running','succeeded','partial','failed','skipped')),
  failed_step text,
  error text,
  attempt integer NOT NULL DEFAULT 1,
  final boolean NOT NULL DEFAULT true,
  analysis_id uuid REFERENCES ci_pull_analyses(id) ON DELETE SET NULL,
  token_id uuid REFERENCES ci_mcp_tokens(id) ON DELETE SET NULL,
  input jsonb,
  summary jsonb,
  result jsonb,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  projected_at timestamptz
);
CREATE INDEX IF NOT EXISTS ci_runs_installation ON ci_runs(installation_id,started_at DESC);
CREATE INDEX IF NOT EXISTS ci_runs_failures ON ci_runs(installation_id,started_at DESC) WHERE status IN ('failed','partial');
CREATE INDEX IF NOT EXISTS ci_runs_unprojected ON ci_runs(started_at) WHERE projected_at IS NULL AND finished_at IS NOT NULL;
CREATE TABLE IF NOT EXISTS ci_run_steps(
  run_id uuid NOT NULL REFERENCES ci_runs(id) ON DELETE CASCADE,
  seq integer NOT NULL,
  name text NOT NULL,
  status text NOT NULL CHECK(status IN ('ok','failed','skipped')),
  started_at timestamptz NOT NULL,
  duration_ms integer NOT NULL,
  detail text,
  PRIMARY KEY(run_id,seq)
);
-- Breaks: each change that breaks (or needs a change in) a repository's code, as found by a pull request
-- check or a scan, with the code at each place, and what became of it.
-- key: "<package>@<to>:<kind>:<symbol>:<parameter>"; pull-request breaks are kept per pull request.
CREATE TABLE IF NOT EXISTS ci_breaks(
  installation_id bigint NOT NULL REFERENCES ci_installations(id) ON DELETE CASCADE,
  repository text NOT NULL,
  source text NOT NULL CHECK(source IN ('pull','scan')),
  pull_number integer NOT NULL DEFAULT 0,
  key text NOT NULL,
  severity text NOT NULL CHECK(severity IN ('breaks','needs-change')),
  package text NOT NULL,
  start_version text NOT NULL,
  end_version text NOT NULL,
  change jsonb NOT NULL,
  decision jsonb,
  places jsonb NOT NULL,
  status text NOT NULL DEFAULT 'open' CHECK(status IN ('open','fixed','merged','closed')),
  analysis_id uuid REFERENCES ci_pull_analyses(id) ON DELETE SET NULL,
  first_run uuid REFERENCES ci_runs(id) ON DELETE SET NULL,
  last_run uuid REFERENCES ci_runs(id) ON DELETE SET NULL,
  first_seen timestamptz NOT NULL DEFAULT now(),
  last_seen timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz,
  PRIMARY KEY(installation_id,repository,source,pull_number,key)
);
CREATE INDEX IF NOT EXISTS ci_breaks_open ON ci_breaks(installation_id,status,last_seen DESC);
-- Same private-ledger posture as the other workspace tables.
DO $$
DECLARE table_name text; role_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['ci_runs','ci_run_steps','ci_breaks'] LOOP
    EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',current_schema(),table_name);
    EXECUTE format('REVOKE ALL ON TABLE %I.%I FROM PUBLIC',current_schema(),table_name);
    FOR role_name IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role') LOOP
      EXECUTE format('REVOKE ALL ON TABLE %I.%I FROM %I',current_schema(),table_name,role_name);
    END LOOP;
  END LOOP;
END $$;
