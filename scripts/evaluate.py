"""Reproducible 30-question evaluation. Automated metrics are not human support proof."""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from codeintent import store
from codeintent.domain import Answer, validate_citations
from codeintent.investigate import investigate, retrieve
from codeintent.settings import ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--answers", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    questions = json.loads((ROOT / "evals/questions.json").read_text())
    if args.limit:
        questions = questions[: args.limit]
    indexed = store.get_index()
    corpus = indexed["corpus"]
    scope = indexed["id"]
    output = ROOT / "artifacts/evaluation"
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    if args.resume and (output / "latest.json").exists():
        previous = json.loads((output / "latest.json").read_text())
        if previous["index_id"] == scope:
            for row in previous["questions"]:
                if (
                    row.get("answer", {}).get("policy_version") != "evidence-v3"
                    or "error_category" in row
                ):
                    continue
                question = next((q for q in questions if q["id"] == row["id"]), None)
                if question and all(row.get(k) == v for k, v in question.items()):
                    rows.append(row)
    completed = {row["id"] for row in rows}
    started = time.time()

    def run(q):
        result = {**q}
        for graph in [False, True]:
            _, sources, paths = retrieve(
                q["question"], corpus, graph=graph, scope=scope
            )
            ids = {s["id"] for s in sources}
            gold = set(q["essential_sources"])
            result["graph" if graph else "without_graph"] = {
                "sources": [s["id"] for s in sources],
                "essential_recall": len(ids & gold) / len(gold) if gold else None,
                "paths": len(paths),
            }
        if args.answers:
            answer = investigate(
                q["question"], corpus, indexed["decisions"], scope=scope
            )
            validate_citations(
                Answer.model_validate(answer["answer"]), answer["sources"]
            )
            result["answer"] = answer
            result["exact_citations_pass"] = True
            result["abstention_pass"] = (
                answer["answer"]["status"] == "insufficient"
                and not answer["answer"]["claims"]
                if q["expected"] == "insufficient"
                else None
            )
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {
            pool.submit(run, q): q for q in questions if q["id"] not in completed
        }
        for future in as_completed(futures):
            q = futures[future]
            try:
                row = future.result()
            except Exception as exc:
                row = {**q, "error_category": type(exc).__name__}
            rows.append(row)
            result = {
                "index_id": scope,
                "policy_version": "evidence-v3",
                "resumed": args.resume,
                "seconds": round(time.time() - started, 2),
                "evaluation": "automated retrieval/contract smoke; semantic support requires human review",
                "questions": sorted(rows, key=lambda x: x["id"]),
            }
            temp = output / "latest.tmp"
            temp.write_text(json.dumps(result, indent=2, default=str))
            temp.replace(output / "latest.json")
            print(
                f"{len(rows)}/{len(questions)} {q['id']} {'failed' if 'error_category' in row else 'complete'}",
                flush=True,
            )


if __name__ == "__main__":
    main()
