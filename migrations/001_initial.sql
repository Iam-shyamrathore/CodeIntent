CREATE TABLE IF NOT EXISTS ci_schema_versions(version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS ci_repositories(
  id bigint PRIMARY KEY, name text UNIQUE NOT NULL, description text NOT NULL DEFAULT '',
  ready_index text, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ci_imports(
  id uuid PRIMARY KEY, repository text NOT NULL, options jsonb NOT NULL,
  status text NOT NULL DEFAULT 'queued', stage text NOT NULL DEFAULT 'queued',
  progress integer NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
  error text, checkpoint jsonb NOT NULL DEFAULT '{}', index_id text,
  cancelled boolean NOT NULL DEFAULT false, task_id bigint,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ci_one_active_import ON ci_imports(repository)
  WHERE status IN ('queued','running','retrying');
CREATE TABLE IF NOT EXISTS ci_indexes(
  id text PRIMARY KEY, repository_id bigint NOT NULL REFERENCES ci_repositories(id),
  revision text NOT NULL, corpus jsonb NOT NULL, decisions jsonb NOT NULL DEFAULT '[]',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ci_reports(
  id uuid PRIMARY KEY, index_id text NOT NULL REFERENCES ci_indexes(id),
  question text NOT NULL, result jsonb NOT NULL, cache_key text UNIQUE NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ci_reports_recent ON ci_reports(created_at DESC);
CREATE TABLE IF NOT EXISTS ci_events(
  id bigserial PRIMARY KEY, import_id uuid NOT NULL REFERENCES ci_imports(id),
  stage text NOT NULL, message text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ci_usage(
  bucket text NOT NULL, day date NOT NULL DEFAULT CURRENT_DATE, count integer NOT NULL DEFAULT 0,
  PRIMARY KEY(bucket,day)
);
CREATE TABLE IF NOT EXISTS ci_workers(name text PRIMARY KEY, heartbeat timestamptz NOT NULL DEFAULT now());
