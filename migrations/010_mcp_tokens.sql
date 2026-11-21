-- MCP access tokens: one installation each, shown once, stored only as a SHA-256 digest.
CREATE TABLE IF NOT EXISTS ci_mcp_tokens(
  id uuid PRIMARY KEY,
  installation_id bigint NOT NULL REFERENCES ci_installations(id) ON DELETE CASCADE,
  token_hash text NOT NULL UNIQUE CHECK(token_hash ~ '^[0-9a-f]{64}$'),
  hint text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_used_at timestamptz,
  revoked_at timestamptz
);
CREATE INDEX IF NOT EXISTS ci_mcp_tokens_installation ON ci_mcp_tokens(installation_id,created_at DESC);
-- Same private-ledger posture as the other workspace tables.
DO $$
DECLARE role_name text;
BEGIN
  EXECUTE format('ALTER TABLE %I.ci_mcp_tokens ENABLE ROW LEVEL SECURITY',current_schema());
  EXECUTE format('REVOKE ALL ON TABLE %I.ci_mcp_tokens FROM PUBLIC',current_schema());
  FOR role_name IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role') LOOP
    EXECUTE format('REVOKE ALL ON TABLE %I.ci_mcp_tokens FROM %I',current_schema(),role_name);
  END LOOP;
END $$;
