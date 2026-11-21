"""Run every labelled case in evals/upgrades.json through the verdict engine and score it.

    python -m scripts.backtest                 # all cases, writes artifacts/backtest/latest.json
    python -m scripts.backtest --only httpx    # cases whose id contains "httpx"

Each consumer is downloaded at its pinned commit (never run). A breaking case counts as caught when the
verdict is "Breaks you", and as localised when a finding points within LINE_SLACK lines of every expected
line. A guarded case is correct when it is not "Breaks you". A harmless case is a false alarm only when it
is "Breaks you"; the other verdicts are reported as a distribution, and "Not checked" is never counted as
correct.
"""

from __future__ import annotations

import argparse
import json
import math
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx

from codeintent.upgrades import repository
from codeintent.upgrades.verdict import evaluate

CASES = Path("evals/upgrades.json")
OUTPUT = Path("artifacts/backtest/latest.json")
LINE_SLACK = 5


def wilson_upper(failures: int, total: int, z: float = 1.96) -> float | None:
    if total == 0:
        return None
    p = failures / total
    centre = p + z * z / (2 * total)
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return round((centre + spread) / (1 + z * z / total), 4)


def localised(case: dict, verdict) -> bool:
    found = [
        (loc.file, loc.line or 0)
        for f in verdict.findings
        if f.severity == "breaks"
        for loc in f.locations
    ]
    return all(
        any(
            file == e["file"] and abs(line - e["line"]) <= LINE_SLACK
            for file, line in found
        )
        for e in case["expected"]
    )


def run(case: dict, client: httpx.Client, secret: str | None) -> dict:
    started = time.time()
    result = {
        "id": case["id"],
        "label": case["label"],
        "package": case["package"],
        "from": case["from"],
        "to": case["to"],
    }
    try:
        with tempfile.TemporaryDirectory(prefix="ci-backtest-") as folder:
            root = repository.download(
                case["consumer"]["repo"],
                case["consumer"]["commit"],
                Path(folder),
                secret,
            )
            verdict = evaluate(
                case["package"], case["from"], case["to"], root, client,
                release=False, advisory=False, upstream=False,
            )  # fmt: skip
    except (
        Exception
    ) as error:  # a case that can't run is reported, never scored as correct
        result.update(
            verdict="error", error=f"{type(error).__name__}: {str(error)[:200]}"
        )
    else:
        result.update(
            verdict=verdict.verdict,
            reason=verdict.reason,
            findings=[
                {
                    "severity": f.severity,
                    "kind": f.change.kind,
                    "symbol": f.change.symbol,
                    "parameter": f.change.parameter,
                    "locations": [f"{loc.file}:{loc.line}" for loc in f.locations[:5]],
                }
                for f in verdict.findings
            ],
            unchecked=sorted({u.reason for u in verdict.unchecked}),
        )
        if case["label"] == "breaks":
            result["localised"] = localised(case, verdict)
    result["seconds"] = round(time.time() - started, 1)
    return result


def summarise(results: list[dict]) -> dict:
    by = {
        label: [r for r in results if r["label"] == label]
        for label in ("breaks", "guarded", "harmless")
    }
    breaks, guarded, harmless = by["breaks"], by["guarded"], by["harmless"]
    ran = [r for r in harmless if r["verdict"] != "error"]
    false_breaks = sum(r["verdict"] == "breaks" for r in ran)
    return {
        "updated": datetime.now(UTC).isoformat(timespec="seconds"),
        "breaks": {
            "total": len(breaks),
            "caught": sum(r["verdict"] == "breaks" for r in breaks),
            "localised": sum(bool(r.get("localised")) for r in breaks),
            "verdicts": dict(Counter(r["verdict"] for r in breaks)),
        },
        "guarded": {
            "total": len(guarded),
            "not_breaks": sum(r["verdict"] not in ("breaks", "error") for r in guarded),
            "verdicts": dict(Counter(r["verdict"] for r in guarded)),
        },
        "harmless": {
            "total": len(harmless),
            "ran": len(ran),
            "false_breaks": false_breaks,
            "wilson_upper": wilson_upper(false_breaks, len(ran)),
            "verdicts": dict(Counter(r["verdict"] for r in harmless)),
        },
        "unchecked_reasons": dict(
            Counter(reason for r in results for reason in r.get("unchecked", []))
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", help="run cases whose id contains this text")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    cases = [
        c
        for c in json.loads(CASES.read_text())
        if not args.only or args.only in c["id"]
    ]
    secret = repository.token()
    results = []
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for index, case in enumerate(cases, 1):
            result = run(case, client, secret)
            results.append(result)
            mark = {
                "breaks": "caught" if result["verdict"] == "breaks" else "MISSED"
            }.get(case["label"], "")
            if case["label"] == "harmless" and result["verdict"] == "breaks":
                mark = "FALSE ALARM"
            print(
                f"[{index}/{len(cases)}] {case['id']}: {result['verdict']} {mark} ({result['seconds']}s)",
                flush=True,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps({"summary": summarise(results), "cases": results}, indent=1)
            )
    print(json.dumps(summarise(results), indent=1))


if __name__ == "__main__":
    main()
