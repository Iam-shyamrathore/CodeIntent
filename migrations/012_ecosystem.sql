-- The public ecosystem graph: which package releases and open-source projects have been indexed into Neo4j.
-- These hold only public data (PyPI, deps.dev, OSV.dev, public GitHub repositories), so they are not
-- workspace-scoped; workspace repositories link into the graph through their locked releases.
CREATE TABLE IF NOT EXISTS ci_ecosystem_releases(
  package text NOT NULL,
  version text NOT NULL,
  status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','indexed','not-found','failed')),
  dependencies integer,
  error text,
  requested_at timestamptz NOT NULL DEFAULT now(),
  indexed_at timestamptz,
  PRIMARY KEY(package,version)
);
CREATE INDEX IF NOT EXISTS ci_ecosystem_releases_status ON ci_ecosystem_releases(status,requested_at);
CREATE TABLE IF NOT EXISTS ci_ecosystem_projects(
  full_name text PRIMARY KEY,
  source text NOT NULL DEFAULT 'seed' CHECK(source IN ('seed','workspace')),
  status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','indexed','skipped','failed')),
  ref text,
  dependencies integer,
  error text,
  requested_at timestamptz NOT NULL DEFAULT now(),
  indexed_at timestamptz
);
DO $$
DECLARE table_name text; role_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['ci_ecosystem_releases','ci_ecosystem_projects'] LOOP
    EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',current_schema(),table_name);
    EXECUTE format('REVOKE ALL ON TABLE %I.%I FROM PUBLIC',current_schema(),table_name);
    FOR role_name IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role') LOOP
      EXECUTE format('REVOKE ALL ON TABLE %I.%I FROM %I',current_schema(),table_name,role_name);
    END LOOP;
  END LOOP;
END $$;
