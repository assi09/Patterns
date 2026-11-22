"""Write the endpoint and schema part of `docs/api.md` from FastAPI's own OpenAPI schema.

Run from the repository root with `.venv` active: `python -m app.api.reference` (rewrites the
generated part of `docs/api.md`), or `--check` to fail when it is out of date. The text around the
markers is written by hand and kept. `tests/test_api_reference.py` fails when a route or schema
changes and the document was not regenerated, so the reference cannot drift from the code.
"""

import argparse
import ast
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute

START = "<!-- generated: start (python -m app.api.reference) -->"
END = "<!-- generated: end -->"
DOC = Path(__file__).resolve().parents[3] / "docs" / "api.md"
APP_DIR = Path(__file__).resolve().parents[1]

# Who may call a route, from the dependency it declares (the strictest one wins).
_ACCESS = [
    ("admin_user", "owner"),
    ("supervisor_user", "supervisor"),
    ("approved_user", "approved"),
    ("current_user", "signed in"),
]
_PLAIN = {"string": "string", "integer": "integer", "number": "number", "boolean": "boolean"}


def access(route: APIRoute) -> str:
    """The access level a route needs, read from its dependency tree."""
    names: set[str] = set()
    stack = list(route.dependant.dependencies)
    while stack:
        dependency = stack.pop()
        if dependency.call is not None:
            names.add(getattr(dependency.call, "__name__", ""))
        stack.extend(dependency.dependencies)
    for name, level in _ACCESS:
        if name in names:
            return level
    return "public"


def type_of(schema: dict[str, Any]) -> str:
    """A short type for a schema: a linked name, `list[...]`, an enum or a plain type."""
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        return f"[{name}](#{name.lower()})"
    if "anyOf" in schema:
        options = [type_of(part) for part in schema["anyOf"] if part.get("type") != "null"]
        nullable = any(part.get("type") == "null" for part in schema["anyOf"])
        text = " or ".join(dict.fromkeys(options)) or "null"
        return f"{text} or null" if nullable else text
    if "enum" in schema:
        return " | ".join(f"`{value}`" for value in schema["enum"])
    if "const" in schema:
        return f"`{schema['const']}`"
    kind = schema.get("type")
    if kind == "array":
        return f"list[{type_of(schema.get('items', {}))}]"
    if kind == "object":
        values = schema.get("additionalProperties")
        if isinstance(values, dict) and values:
            return f"map[string, {type_of(values)}]"
        return "object"
    if kind in _PLAIN:
        fmt = schema.get("format")
        return f"{_PLAIN[kind]} ({fmt})" if fmt else _PLAIN[kind]
    return "any"


def _limits(schema: dict[str, Any]) -> str:
    parts = []
    for key, label in [
        ("minLength", "min length"),
        ("maxLength", "max length"),
        ("minimum", "≥"),
        ("maximum", "≤"),
        ("minItems", "min items"),
        ("maxItems", "max items"),
    ]:
        if key in schema:
            parts.append(f"{label} {schema[key]}")
    if "default" in schema and schema["default"] is not None:
        parts.append(f"default `{schema['default']}`")
    return ", ".join(parts)


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def _summary(route: APIRoute) -> str:
    doc = (route.description or "").strip()
    return _cell(doc.split("\n\n", 1)[0]) if doc else ""


def _body(route: APIRoute, operation: dict[str, Any]) -> str:
    content = operation.get("requestBody", {}).get("content", {})
    for media, item in content.items():
        text = type_of(item.get("schema", {}))
        return text if media == "application/json" else f"{text} ({media})"
    return ""


def _returns(operation: dict[str, Any]) -> str:
    for status in sorted(operation.get("responses", {})):
        if not status.startswith("2"):
            continue
        response = operation["responses"][status]
        content = response.get("content", {}).get("application/json")
        if status == "204" or not content or not content.get("schema"):
            return f"{status}, no body"
        text = type_of(content["schema"])
        return text if status == "200" else f"{status}: {text}"
    return ""


def _parameters(operation: dict[str, Any]) -> str:
    names = []
    for parameter in operation.get("parameters", []):
        if parameter["in"] == "header":
            continue
        name = f"`{parameter['name']}`"
        if parameter["in"] == "query":
            name += "?" if not parameter.get("required") else ""
        names.append(name)
    return ", ".join(names)


def _routes(routes: Iterable[Any]) -> Iterable[APIRoute]:
    # FastAPI 0.148 keeps an included router as one entry pointing at the original router
    # (main.py includes them with no prefix or dependencies, so its routes are used as they are).
    for route in routes:
        if isinstance(route, APIRoute):
            if route.include_in_schema:
                yield route
        elif hasattr(route, "original_router"):
            yield from _routes(route.original_router.routes)


def endpoints(app: FastAPI, spec: dict[str, Any]) -> list[str]:
    by_tag: dict[str, list[str]] = {}
    for route in _routes(app.routes):
        tag = (route.tags or ["other"])[0]
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            operation = spec["paths"][route.path_format][method.lower()]
            row = [
                f"`{method}`",
                f"`{route.path_format}`",
                access(route),
                _parameters(operation),
                _body(route, operation),
                _returns(operation),
                _summary(route),
            ]
            by_tag.setdefault(tag, []).append("| " + " | ".join(map(_cell, row)) + " |")
    lines = ["## Endpoints", ""]
    lines.append(f"{sum(len(rows) for rows in by_tag.values())} operations, grouped by area.")
    lines.append("")
    for tag, rows in by_tag.items():
        lines += [f"### {tag}", ""]
        lines.append("| Method | Path | Access | Parameters | Body | Returns | Notes |")
        lines.append("|---|---|---|---|---|---|---|")
        lines += rows
        lines.append("")
    return lines


def schemas(spec: dict[str, Any]) -> list[str]:
    skip = {"HTTPValidationError", "ValidationError"}
    lines = ["## Schemas", ""]
    lines.append("Field names are as sent on the wire (camelCase where the app expects it).")
    lines += ["A field not marked required may be left out.", ""]
    for name, schema in sorted(spec["components"]["schemas"].items()):
        if name in skip:
            continue
        lines += [f"### {name}", ""]
        if schema.get("description"):
            lines += [_cell(schema["description"]), ""]
        properties = schema.get("properties", {})
        if not properties:
            lines += [f"Type: {type_of(schema)}.", ""]
            continue
        required = set(schema.get("required", []))
        lines.append("| Field | Type | Required | Limits |")
        lines.append("|---|---|---|---|")
        for field, part in properties.items():
            mark = "yes" if field in required else ""
            cells = [f"`{field}`", type_of(part), mark, _limits(part)]
            lines.append("| " + " | ".join(map(_cell, cells)) + " |")
        lines.append("")
    return lines


def error_codes(root: Path = APP_DIR) -> list[tuple[int, str]]:
    """Every `ApiError(status, code, …)` and `AuthError(status, code, …)` with literal values."""
    found: set[tuple[int, str]] = set()
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or len(node.args) < 2:
                continue
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            status, code = node.args[0], node.args[1]
            if (
                name in {"ApiError", "AuthError"}
                and isinstance(status, ast.Constant)
                and isinstance(status.value, int)
                and isinstance(code, ast.Constant)
                and isinstance(code.value, str)
            ):
                found.add((status.value, code.value))
    return sorted(found)


def errors() -> list[str]:
    lines = ["## Error codes", ""]
    lines.append("Raised in the code with a fixed status and code (the message varies by case).")
    lines += ["", "| Status | Code |", "|---|---|"]
    lines += [f"| {status} | `{code}` |" for status, code in error_codes()]
    lines.append("")
    return lines


def generated(app: FastAPI) -> str:
    spec = app.openapi()
    lines = [START, ""] + endpoints(app, spec) + errors() + schemas(spec) + [END]
    return "\n".join(lines)


def render(current: str, app: FastAPI) -> str:
    """The document with its generated part replaced; the hand-written parts are kept."""
    if START not in current or END not in current:
        raise ValueError(f"{DOC} has no generated markers")
    head, rest = current.split(START, 1)
    _, tail = rest.split(END, 1)
    return head + generated(app) + tail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="fail if docs/api.md is stale")
    args = parser.parse_args(argv)

    from app.api.main import app

    current = DOC.read_text(encoding="utf-8")
    updated = render(current, app)
    if args.check:
        if updated != current:
            print("docs/api.md is out of date: run python -m app.api.reference", file=sys.stderr)
            return 1
        return 0
    DOC.write_text(updated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
