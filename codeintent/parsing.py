"""Direct Tree-sitter adapter. Only unambiguous calls in the same file are resolved."""

from pathlib import PurePosixPath

from tree_sitter_language_pack import get_parser

LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
}
DEFINITIONS = {
    "function_definition",
    "function_declaration",
    "method_definition",
    "method_declaration",
    "function_item",
}
CLASSES = {
    "class_definition",
    "class_declaration",
    "struct_item",
    "interface_declaration",
}


def parse_sources(documents: list[dict]) -> list[dict]:
    result = []
    for source in documents:
        path = source.get("path", "")
        language = LANGUAGES.get(PurePosixPath(path).suffix)
        if source["kind"] != "code" or not language:
            continue
        raw = source["body"].encode()
        tree = get_parser(language).parse(raw)
        row = {
            "path": path,
            "functions": [],
            "classes": [],
            "function_calls": [],
            "imports": [],
            "source_id": source["id"],
            "parse_errors": tree.root_node.has_error,
        }
        stack = [(tree.root_node, "")]
        while stack:
            node, context = stack.pop()
            name = node.child_by_field_name("name")
            title = raw[name.start_byte : name.end_byte].decode() if name else ""
            value = node.child_by_field_name("value")
            arrow = (
                node.type == "variable_declarator"
                and value is not None
                and value.type == "arrow_function"
            )
            if (node.type in DEFINITIONS | CLASSES or arrow) and title:
                item = {
                    "name": title,
                    "line_number": node.start_point.row + 1,
                    "end_line": node.end_point.row + 1,
                    "class_context": context,
                }
                row["classes" if node.type in CLASSES else "functions"].append(item)
                context = (context + "." + title).strip(".")
            if node.type in {"call", "call_expression"}:
                fn = node.child_by_field_name("function")
                if fn and fn.type == "identifier":
                    row["function_calls"].append(
                        {
                            "name": raw[fn.start_byte : fn.end_byte].decode(),
                            "line_number": node.start_point.row + 1,
                            "context": context,
                        }
                    )
            if node.type in {
                "import_statement",
                "import_from_statement",
                "import_declaration",
                "use_declaration",
            }:
                row["imports"].append(
                    {
                        "text": raw[node.start_byte : node.end_byte].decode()[:500],
                        "line_number": node.start_point.row + 1,
                    }
                )
            stack.extend((child, context) for child in reversed(node.named_children))
        result.append(row)
    return result
