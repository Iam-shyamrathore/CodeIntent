-- Agents: Gemini working on top of the deterministic facts. Their output is stored apart from verdicts and
-- always shown as an agent's, with the model and its sources.
-- Agent work is recorded as runs too, so failures show on the dashboard like any other run.
ALTER TABLE ci_runs DROP CONSTRAINT IF EXISTS ci_runs_kind_check;
ALTER TABLE ci_runs ADD CONSTRAINT ci_runs_kind_check CHECK(kind IN ('pull','scan','mcp','agent'));
-- One review per pull request check: proposed patches, assessments of uses static analysis could not
-- follow, and behaviour changes in the release notes that touch code the repository calls.
CREATE TABLE IF NOT EXISTS ci_agent_reviews(
  run_id uuid PRIMARY KEY REFERENCES ci_runs(id) ON DELETE CASCADE,
  installation_id bigint NOT NULL REFERENCES ci_installations(id) ON DELETE CASCADE,
  repository text NOT NULL,
  pull_number integer NOT NULL,
  model text NOT NULL,
  result jsonb NOT NULL,
  trace jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ci_agent_reviews_pull ON ci_agent_reviews(installation_id,repository,pull_number,created_at DESC);
-- Security news found on the web for the packages a workspace locks, before or beside OSV.dev.
-- affects: whether the locked version falls in the reported range ('maybe' when no range was given).
CREATE TABLE IF NOT EXISTS ci_security_news(
  installation_id bigint NOT NULL REFERENCES ci_installations(id) ON DELETE CASCADE,
  package text NOT NULL,
  key text NOT NULL,
  item jsonb NOT NULL,
  affects text NOT NULL CHECK(affects IN ('yes','maybe','no')),
  in_osv boolean NOT NULL DEFAULT false,
  repositories text[] NOT NULL DEFAULT '{}',
  first_seen timestamptz NOT NULL DEFAULT now(),
  last_seen timestamptz NOT NULL DEFAULT now(),
  alerted_at timestamptz,
  PRIMARY KEY(installation_id,package,key)
);
CREATE INDEX IF NOT EXISTS ci_security_news_recent ON ci_security_news(installation_id,last_seen DESC);
DO $$
DECLARE table_name text; role_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['ci_agent_reviews','ci_security_news'] LOOP
    EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',current_schema(),table_name);
    EXECUTE format('REVOKE ALL ON TABLE %I.%I FROM PUBLIC',current_schema(),table_name);
    FOR role_name IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role') LOOP
      EXECUTE format('REVOKE ALL ON TABLE %I.%I FROM %I',current_schema(),table_name,role_name);
    END LOOP;
  END LOOP;
END $$;
