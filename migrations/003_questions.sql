CREATE TABLE ci_questions (
  id uuid PRIMARY KEY, cache_key text UNIQUE NOT NULL,
  index_id text NOT NULL REFERENCES ci_indexes(id), question text NOT NULL,
  status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','retrying','ready','failed')),
  report_id uuid REFERENCES ci_reports(id), error text, task_id bigint,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
