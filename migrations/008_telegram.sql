-- Telegram: chats linked to a GitHub App installation, and the alerts already sent to them.
-- One-time link codes are stored only as SHA-256 hex digests; the code itself is shown once to the operator.
CREATE TABLE IF NOT EXISTS ci_telegram_links(
  code_hash text PRIMARY KEY CHECK(code_hash ~ '^[0-9a-f]{64}$'),
  installation_id bigint NOT NULL REFERENCES ci_installations(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  used_at timestamptz
);
CREATE INDEX IF NOT EXISTS ci_telegram_links_installation ON ci_telegram_links(installation_id,created_at DESC);
CREATE TABLE IF NOT EXISTS ci_telegram_chats(
  chat_id bigint NOT NULL,
  installation_id bigint NOT NULL REFERENCES ci_installations(id) ON DELETE CASCADE,
  linked_at timestamptz NOT NULL DEFAULT now(),
  title text,
  PRIMARY KEY(chat_id,installation_id)
);
CREATE INDEX IF NOT EXISTS ci_telegram_chats_installation ON ci_telegram_chats(installation_id);
-- Each analysis alerts each chat at most once: the row is claimed before sending.
CREATE TABLE IF NOT EXISTS ci_telegram_alerts(
  analysis_id uuid NOT NULL REFERENCES ci_pull_analyses(id) ON DELETE CASCADE,
  chat_id bigint NOT NULL,
  sent_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(analysis_id,chat_id)
);
-- Same private-ledger posture as 004 and 006.
DO $$
DECLARE table_name text; role_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['ci_telegram_links','ci_telegram_chats','ci_telegram_alerts'] LOOP
    EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',current_schema(),table_name);
    EXECUTE format('REVOKE ALL ON TABLE %I.%I FROM PUBLIC',current_schema(),table_name);
    FOR role_name IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role') LOOP
      EXECUTE format('REVOKE ALL ON TABLE %I.%I FROM %I',current_schema(),table_name,role_name);
    END LOOP;
  END LOOP;
END $$;
