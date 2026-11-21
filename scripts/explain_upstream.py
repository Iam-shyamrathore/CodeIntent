"""Print the upstream pull request behind each API change of one upgrade as JSON.

python -m scripts.explain_upstream --package httpx --from 0.27.2 --to 0.28.0 --consumer-path ./checkout
python -m scripts.explain_upstream --package setuptools --from 71.1.0 --to 72.0.0 \
    --symbol setuptools.command.test --kind removed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

from codeintent.upgrades.models import APIChange, Location
from codeintent.upgrades.releases import locate
from codeintent.upgrades.upstream import explain
from codeintent.upgrades.verdict import evaluate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--package", required=True)
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--consumer-path", type=Path, help="checkout whose findings to explain"
    )
    source.add_argument("--symbol", help="explain one hand-written change instead")
    parser.add_argument("--kind", default="removed")
    parser.add_argument("--parameter")
    parser.add_argument("--message")
    parser.add_argument("--file", help="file of the symbol in the old release")
    args = parser.parse_args(argv)
    stats: dict = {}
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        if args.consumer_path:
            verdict = evaluate(
                args.package,
                args.start,
                args.end,
                args.consumer_path,
                client,
                advisory=False,
            )
            release = verdict.release
            changes = [f.change for f in verdict.findings]
        else:
            release = locate(args.package, args.start, args.end, client)
            changes = [
                APIChange(
                    kind=args.kind,
                    symbol=args.symbol,
                    parameter=args.parameter,
                    detail=f"{args.symbol} given on the command line",
                    message=args.message,
                    before=Location(file=args.file) if args.file else None,
                )
            ]
        decisions = explain(release, changes, client, stats=stats)
    print(
        json.dumps(
            {
                "release": release.model_dump(mode="json", exclude_none=True),
                "decisions": [
                    d.model_dump(mode="json", exclude_none=True) for d in decisions
                ],
                "github": stats,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
