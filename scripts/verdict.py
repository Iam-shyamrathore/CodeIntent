"""Print the upgrade verdict for one package in one repository as JSON.

python -m scripts.verdict --repo owner/name@ref --package httpx --from 0.27.2 --to 0.28.0
python -m scripts.verdict --path ./checkout --package httpx --from 0.27.2 --to 0.28.0
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

from codeintent.upgrades import repository
from codeintent.upgrades.verdict import evaluate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--repo", help="owner/name@ref on GitHub")
    source.add_argument("--path", type=Path, help="a local checkout")
    parser.add_argument("--package", required=True)
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument(
        "--no-release", action="store_true", help="skip locating upstream tags"
    )
    parser.add_argument(
        "--no-advisories", action="store_true", help="skip OSV.dev lookups"
    )
    args = parser.parse_args(argv)
    options = {"release": not args.no_release, "advisory": not args.no_advisories}
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        if args.path:
            result = evaluate(
                args.package, args.start, args.end, args.path, client, **options
            )
        else:
            name, _, ref = args.repo.partition("@")
            with repository.temporary() as folder:
                root = repository.download(
                    name, ref or "HEAD", Path(folder), repository.token()
                )
                result = evaluate(
                    args.package, args.start, args.end, root, client, **options
                )
    print(result.model_dump_json(indent=2, exclude_none=True))
    return {"breaks": 1, "not-checked": 2}.get(result.verdict, 0)


if __name__ == "__main__":
    sys.exit(main())
