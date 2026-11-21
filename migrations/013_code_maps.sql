-- Code maps: the latest map of each repository's default branch (files, local imports, functions, resolved
-- calls, tests, entry points and every use of each dependency). The workspace graph in Neo4j is projected
-- from these rows, so it can always be rebuilt from PostgreSQL.
CREATE TABLE IF NOT EXISTS ci_code_maps(
  installation_id bigint NOT NULL REFERENCES ci_installations(id) ON DELETE CASCADE,
  repository text NOT NULL,
  sha text NOT NULL,
  map jsonb NOT NULL,
  built_at timestamptz NOT NULL DEFAULT now(),
  projected_at timestamptz,
  PRIMARY KEY(installation_id,repository)
);
DO $$
DECLARE role_name text;
BEGIN
  EXECUTE format('ALTER TABLE %I.ci_code_maps ENABLE ROW LEVEL SECURITY',current_schema());
  EXECUTE format('REVOKE ALL ON TABLE %I.ci_code_maps FROM PUBLIC',current_schema());
  FOR role_name IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role') LOOP
    EXECUTE format('REVOKE ALL ON TABLE %I.ci_code_maps FROM %I',current_schema(),role_name);
  END LOOP;
END $$;
