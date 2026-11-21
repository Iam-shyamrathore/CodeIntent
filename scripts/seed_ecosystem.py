"""Queue the real open-source projects of the labelled backtest set into the public ecosystem graph.

    python -m scripts.seed_ecosystem            # every consumer repository in evals/upgrades.json
    python -m scripts.seed_ecosystem owner/name  # just these

Only each project's manifest and lock files are read, through the GitHub API; nothing is downloaded or run.
The worker then indexes every release they depend on, transitively.
"""

from __future__ import annotations

import json
import sys

from codeintent import store
from codeintent.settings import ROOT


def main(names: list[str]) -> None:
    from codeintent.tasks import seed_project

    if not names:
        cases = json.loads((ROOT / "evals" / "upgrades.json").read_text())
        names = sorted({c["consumer"]["repo"] for c in cases})
    queued = 0
    with store.connection() as conn:
        for name in names:
            conn.execute(
                """INSERT INTO ci_ecosystem_projects(full_name,status) VALUES (%s,'queued')
                ON CONFLICT(full_name) DO UPDATE SET status='queued',requested_at=now()""",
                (name,),
            )
            try:
                with conn.transaction():
                    seed_project.configure(
                        connection=conn, queueing_lock=f"seed:{name}", priority=-15
                    ).defer(full_name=name)
                queued += 1
            except Exception as exc:
                print(f"{name}: not queued ({type(exc).__name__})")
    print(f"Queued {queued} of {len(names)} projects")


if __name__ == "__main__":
    main(sys.argv[1:])
