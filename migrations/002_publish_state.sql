ALTER TABLE ci_indexes ADD COLUMN IF NOT EXISTS published_at timestamptz;
UPDATE ci_indexes SET published_at=created_at
WHERE published_at IS NULL AND (id IN (SELECT ready_index FROM ci_repositories) OR id IN (SELECT index_id FROM ci_reports));
