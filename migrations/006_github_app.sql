-- GitHub App workspaces. A workspace is one App installation; every row of
-- workspace data carries installation_id.
CREATE TABLE IF NOT EXISTS ci_installations(
  id bigint PRIMARY KEY, account_login text NOT NULL, account_type text NOT NULL,
  suspended boolean NOT NULL DEFAULT false, deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ci_installation_repositories(
  installation_id bigint NOT NULL REFERENCES ci_installations(id) ON DELETE CASCADE,
  repository_id bigint NOT NULL, full_name text NOT NULL, private boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(installation_id,repository_id)
);
CREATE INDEX IF NOT EXISTS ci_installation_repositories_name ON ci_installation_repositories(full_name);
-- One row per X-GitHub-Delivery GUID: re-deliveries are acknowledged without reprocessing.
CREATE TABLE IF NOT EXISTS ci_webhook_deliveries(
  id text PRIMARY KEY, installation_id bigint, event text NOT NULL, action text,
  received_at timestamptz NOT NULL DEFAULT now(),
  status text NOT NULL DEFAULT 'received' CHECK(status IN ('received','processed','queued','ignored','failed')),
  error text
);
CREATE INDEX IF NOT EXISTS ci_webhook_deliveries_recent ON ci_webhook_deliveries(received_at DESC);
CREATE TABLE IF NOT EXISTS ci_pull_analyses(
  id uuid PRIMARY KEY, installation_id bigint NOT NULL REFERENCES ci_installations(id),
  repository text NOT NULL, number integer NOT NULL CHECK(number > 0),
  head_sha text NOT NULL, base_sha text NOT NULL,
  status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','retrying','diffed','skipped','failed')),
  diff jsonb, error text, delivery_id text REFERENCES ci_webhook_deliveries(id), task_id bigint,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(repository,number,head_sha)
);
CREATE INDEX IF NOT EXISTS ci_pull_analyses_installation ON ci_pull_analyses(installation_id,created_at DESC);
-- Same private-ledger posture as 004 for the new tables.
DO $$
DECLARE table_name text; role_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['ci_installations','ci_installation_repositories','ci_webhook_deliveries','ci_pull_analyses'] LOOP
    EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',current_schema(),table_name);
    EXECUTE format('REVOKE ALL ON TABLE %I.%I FROM PUBLIC',current_schema(),table_name);
    FOR role_name IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role') LOOP
      EXECUTE format('REVOKE ALL ON TABLE %I.%I FROM %I',current_schema(),table_name,role_name);
    END LOOP;
  END LOOP;
END $$;
