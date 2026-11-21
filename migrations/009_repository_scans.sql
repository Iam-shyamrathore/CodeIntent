-- Upcoming breakage: the latest scan of each watched repository's default branch, comparing every
-- direct dependency's locked version with its latest release, before any pull request exists.
-- items: JSON array of codeintent.upgrades.upcoming.Upcoming (model_dump(mode="json")).
CREATE TABLE IF NOT EXISTS ci_repository_scans(
  installation_id bigint NOT NULL REFERENCES ci_installations(id) ON DELETE CASCADE,
  repository text NOT NULL,
  status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','done','skipped','failed')),
  ref text, head_sha text, items jsonb, error text,
  scanned_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(installation_id,repository)
);
-- Each finding alerts each chat once: "breaks:httpx@0.28.1" or "advisory:requests@2.31.0:GHSA-…".
CREATE TABLE IF NOT EXISTS ci_upcoming_alerts(
  installation_id bigint NOT NULL REFERENCES ci_installations(id) ON DELETE CASCADE,
  repository text NOT NULL, key text NOT NULL, chat_id bigint NOT NULL,
  sent_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(installation_id,repository,key,chat_id)
);
-- Same private-ledger posture as 004, 006 and 008.
DO $$
DECLARE table_name text; role_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['ci_repository_scans','ci_upcoming_alerts'] LOOP
    EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',current_schema(),table_name);
    EXECUTE format('REVOKE ALL ON TABLE %I.%I FROM PUBLIC',current_schema(),table_name);
    FOR role_name IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role') LOOP
      EXECUTE format('REVOKE ALL ON TABLE %I.%I FROM %I',current_schema(),table_name,role_name);
    END LOOP;
  END LOOP;
END $$;
