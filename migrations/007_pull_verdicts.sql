-- Verdicts for each dependency a pull request changes, and the GitHub check run and comment that show them.
-- verdicts: JSON array of codeintent.upgrades.verdict.UpgradeVerdict (model_dump(mode="json")), one per changed package.
-- verdict: the worst verdict across them (breaks > not-checked > needs-change > no-known-impact), for listing.
ALTER TABLE ci_pull_analyses DROP CONSTRAINT IF EXISTS ci_pull_analyses_status_check;
ALTER TABLE ci_pull_analyses ADD CONSTRAINT ci_pull_analyses_status_check
  CHECK(status IN ('queued','running','retrying','diffed','skipped','analysed','reported','failed'));
ALTER TABLE ci_pull_analyses ADD COLUMN IF NOT EXISTS verdicts jsonb;
ALTER TABLE ci_pull_analyses ADD COLUMN IF NOT EXISTS verdict text
  CHECK(verdict IS NULL OR verdict IN ('breaks','not-checked','needs-change','no-known-impact'));
ALTER TABLE ci_pull_analyses ADD COLUMN IF NOT EXISTS check_run_id bigint;
ALTER TABLE ci_pull_analyses ADD COLUMN IF NOT EXISTS comment_id bigint;
ALTER TABLE ci_pull_analyses ADD COLUMN IF NOT EXISTS title text;
CREATE INDEX IF NOT EXISTS ci_pull_analyses_repository ON ci_pull_analyses(installation_id,repository,created_at DESC);
