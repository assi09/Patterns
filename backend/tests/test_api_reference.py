"""docs/api.md is generated from the API itself; these keep it from drifting from the code."""

from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from app.api import reference
from app.api.main import app


def test_docs_api_md_is_up_to_date():
    current = reference.DOC.read_text(encoding="utf-8")
    assert reference.render(current, app) == current, (
        "docs/api.md is out of date: run `python -m app.api.reference` from the repository root"
    )


def test_every_documented_route_is_in_the_schema_and_vice_versa():
    spec = app.openapi()
    documented = {
        (method, route.path_format)
        for route in reference._routes(app.routes)
        for method in route.methods - {"HEAD", "OPTIONS"}
    }
    in_schema = {
        (method.upper(), path)
        for path, operations in spec["paths"].items()
        for method in operations
    }
    assert documented == in_schema


def _route(path: str, method: str) -> APIRoute:
    for route in reference._routes(app.routes):
        if route.path_format == path and method in route.methods:
            return route
    raise AssertionError(f"no route {method} {path}")


@pytest.mark.parametrize(
    ("method", "path", "level"),
    [
        ("GET", "/health", "public"),
        ("POST", "/auth/login", "public"),
        ("GET", "/auth/me", "signed in"),
        ("POST", "/chat", "approved"),
        ("GET", "/admin/access-requests", "owner"),
        ("POST", "/teams", "supervisor"),
    ],
)
def test_access_levels_follow_the_dependencies(method, path, level):
    assert reference.access(_route(path, method)) == level


def test_no_route_that_reads_personal_data_is_public():
    public = {
        route.path_format
        for route in reference._routes(app.routes)
        if reference.access(route) == "public"
    }
    assert public <= {"/health", "/auth/signup", "/auth/login", "/auth/logout"}


def test_error_codes_are_read_from_literal_calls(tmp_path: Path):
    (tmp_path / "module.py").write_text(
        "raise ApiError(409, 'busy', 'x')\n"
        "raise errors.AuthError(\n    401, 'signed_out', 'y'\n)\n"
        "raise ApiError(status, 'dynamic', 'z')\n",
        encoding="utf-8",
    )
    assert reference.error_codes(tmp_path) == [(401, "signed_out"), (409, "busy")]


def test_render_refuses_a_document_without_markers():
    with pytest.raises(ValueError):
        reference.render("# no markers", app)


def test_types_are_short_and_linked():
    assert reference.type_of({"$ref": "#/components/schemas/Day"}) == "[Day](#day)"
    nullable = {"anyOf": [{"type": "string", "format": "uuid"}, {"type": "null"}]}
    assert reference.type_of(nullable) == "string (uuid) or null"
    listed = {"type": "array", "items": {"$ref": "#/components/schemas/Point"}}
    assert reference.type_of(listed) == "list[[Point](#point)]"
    assert reference.type_of({"enum": ["quick", "deep"]}) == "`quick` | `deep`"
