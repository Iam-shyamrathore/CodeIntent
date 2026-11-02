"""Run with the isolated, pinned CodeGraphContext environment."""

import json
import time
from pathlib import Path

from codegraphcontext.tools.tree_sitter_parser import TreeSitterParser

root = Path(__file__).resolve().parents[1]
repository = root / ".external/httpx"
parser = TreeSitterParser("python")
started = time.perf_counter()
rows = []
for relative in ["httpx/_urls.py", "httpx/_client.py"]:
    result = parser.parse(repository / relative)
    result["path"] = relative
    rows.append(result)
(root / ".data").mkdir(exist_ok=True)
(root / ".data/parsed-code.json").write_text(json.dumps(rows, default=str))
stats = {
    "seconds": round(time.perf_counter() - started, 3),
    "files": len(rows),
    "functions": sum(len(r["functions"]) for r in rows),
    "classes": sum(len(r["classes"]) for r in rows),
    "call_sites": sum(len(r["function_calls"]) for r in rows),
}
(root / ".data/parser-check.json").write_text(json.dumps(stats, indent=2))
print(json.dumps(stats))
