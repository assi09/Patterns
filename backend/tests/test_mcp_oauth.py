# ruff: noqa: F811 (the fixtures imported from test_checkin)
"""OAuth sign-in for MCP assistants (docs/mcp.md): the whole flow through the real routes, as
claude.ai or `codex mcp login` would run it, and every way it must refuse."""

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select
from test_checkin import client, engine, make_team, signed_in  # noqa: F401

from app.api import chat, main
from app.db.models import AccessToken, OAuthClient, User
from app.db.session import session_scope
from app.harness import oauth

REDIRECT = "http://127.0.0.1:5555/callback"
MCP_HEAD = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}


@pytest.fixture
def api(engine, client, monkeypatch):
    client.app.dependency_overrides[chat.get_sessions] = lambda: lambda: session_scope(engine)
    clock = {"now": datetime.now(UTC)}  # the SDK checks expiry against the wall clock
    monkeypatch.setattr(oauth, "_now", lambda: clock["now"])
    monkeypatch.setattr(main.settings, "reminders_enabled", False)
    make_team(engine)
    client.clock = clock
    with client:  # starts the MCP server's sessions, as the API's startup does
        yield client


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).decode().rstrip("=")


def register(api, name="Codex", redirect=REDIRECT) -> str:
    made = api.post(
        "/register",
        json={
            "client_name": name,
            "redirect_uris": [redirect],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )
    assert made.status_code == 201, made.text
    return made.json()["client_id"]


def start(api, client_id, challenge, redirect=REDIRECT, state="xyz"):
    return api.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        },
        follow_redirects=False,
    )


def request_id(response) -> str:
    assert response.status_code == 302, response.text
    location = urlparse(response.headers["location"])
    assert location.path == "/connect"
    return parse_qs(location.query)["request"][0]


def allow(api, headers, rid, yes=True):
    return api.post(f"/oauth/requests/{rid}", headers=headers, json={"allow": yes})


def code_of(decision) -> dict:
    assert decision.status_code == 200, decision.text
    return {k: v[0] for k, v in parse_qs(urlparse(decision.json()["redirectTo"]).query).items()}


def exchange(api, client_id, code, verifier):
    return api.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )


def signed_in_tokens(api, engine, email="boss@example.com", name="Codex"):
    client_id = register(api, name)
    verifier, challenge = pkce()
    rid = request_id(start(api, client_id, challenge))
    got = code_of(allow(api, signed_in(api, engine, email), rid))
    tokens = exchange(api, client_id, got["code"], verifier)
    assert tokens.status_code == 200, tokens.text
    return client_id, tokens.json()


def mcp_status(api, access: str) -> int:
    head = MCP_HEAD | {"Authorization": f"Bearer {access}"}
    return api.post("/mcp/", json=LIST_TOOLS, headers=head).status_code


def test_an_assistant_finds_the_sign_in_from_the_mcp_address(api):
    refused = api.post("/mcp/", json=LIST_TOOLS, headers=MCP_HEAD)
    assert refused.status_code == 401
    assert "/.well-known/oauth-protected-resource/mcp" in refused.headers["www-authenticate"]
    resource = api.get("/.well-known/oauth-protected-resource/mcp").json()
    server = api.get("/.well-known/oauth-authorization-server").json()
    assert resource["authorization_servers"] == [server["issuer"].rstrip("/")] or resource[
        "authorization_servers"
    ] == [server["issuer"]]
    for endpoint in ("authorization_endpoint", "token_endpoint", "registration_endpoint"):
        assert endpoint in server
    assert "S256" in server["code_challenge_methods_supported"]


def test_signing_in_end_to_end_gives_a_connection_like_a_pasted_token(api, engine):
    client_id = register(api, "Codex")
    verifier, challenge = pkce()
    rid = request_id(start(api, client_id, challenge))
    boss = signed_in(api, engine, "boss@example.com")
    shown = api.get(f"/oauth/requests/{rid}", headers=boss).json()
    assert shown["clientName"] == "Codex" and shown["redirectHost"] == "127.0.0.1"
    got = code_of(allow(api, boss, rid))
    assert got["state"] == "xyz" and got["code"]
    made = exchange(api, client_id, got["code"], verifier)
    assert made.status_code == 200, made.text
    tokens = made.json()
    assert tokens["access_token"].startswith("oat_") and tokens["refresh_token"].startswith("ort_")
    assert tokens["expires_in"] == 3600 and tokens["token_type"].lower() == "bearer"
    assert mcp_status(api, tokens["access_token"]) == 200
    listed = api.get("/me/tokens", headers=boss).json()
    assert [(t["name"], t["signedIn"]) for t in listed] == [("Codex", True)]
    with session_scope(engine) as db:  # only hashes are kept
        row = db.scalar(select(AccessToken))
        assert tokens["access_token"] not in (row.token_hash, row.refresh_hash)


def test_a_code_works_once_and_only_with_its_verifier(api, engine):
    client_id = register(api)
    verifier, challenge = pkce()
    rid = request_id(start(api, client_id, challenge))
    got = code_of(allow(api, signed_in(api, engine, "boss@example.com"), rid))
    assert exchange(api, client_id, got["code"], "wrong-" + verifier).status_code == 400
    assert exchange(api, client_id, got["code"], verifier).status_code == 200
    again = exchange(api, client_id, got["code"], verifier)
    assert again.status_code == 400 and again.json()["error"] == "invalid_grant"


def test_a_code_cannot_be_used_by_another_assistant(api, engine):
    mine, theirs = register(api, "Codex"), register(api, "Other")
    verifier, challenge = pkce()
    rid = request_id(start(api, mine, challenge))
    got = code_of(allow(api, signed_in(api, engine, "boss@example.com"), rid))
    assert exchange(api, theirs, got["code"], verifier).status_code == 400


def test_deny_sends_the_assistant_away_with_nothing(api, engine):
    client_id = register(api)
    _, challenge = pkce()
    rid = request_id(start(api, client_id, challenge))
    got = code_of(allow(api, signed_in(api, engine, "boss@example.com"), rid, yes=False))
    assert got == {"error": "access_denied", "state": "xyz"}
    with session_scope(engine) as db:
        assert db.scalar(select(AccessToken)) is None


def test_a_sign_in_is_answered_once_and_expires(api, engine):
    client_id = register(api)
    _, challenge = pkce()
    boss = signed_in(api, engine, "boss@example.com")
    rid = request_id(start(api, client_id, challenge))
    assert allow(api, boss, rid).status_code == 200
    assert allow(api, boss, rid).status_code == 409
    late = request_id(start(api, client_id, challenge))
    api.clock["now"] += oauth.REQUEST_TTL + timedelta(seconds=1)
    assert api.get(f"/oauth/requests/{late}", headers=boss).status_code == 410
    assert allow(api, boss, late).status_code == 410
    assert api.get("/oauth/requests/not-a-request", headers=boss).status_code == 404


def test_an_unregistered_return_address_is_refused_before_anyone_is_asked(api):
    client_id = register(api)
    _, challenge = pkce()
    refused = start(api, client_id, challenge, redirect="https://evil.example/steal")
    assert refused.status_code == 400
    assert "location" not in refused.headers


def test_hr_cannot_connect_an_assistant_and_signing_in_needs_an_account(api, engine):
    client_id = register(api)
    _, challenge = pkce()
    rid = request_id(start(api, client_id, challenge))
    assert allow(api, {}, rid).status_code == 401
    refused = allow(api, signed_in(api, engine, "hr@example.com"), rid)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "cannot_connect"


def test_refreshing_rotates_both_tokens(api, engine):
    client_id, first = signed_in_tokens(api, engine)
    renewed = api.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": first["refresh_token"],
            "client_id": client_id,
        },
    )
    assert renewed.status_code == 200, renewed.text
    second = renewed.json()
    assert second["access_token"] != first["access_token"]
    assert mcp_status(api, second["access_token"]) == 200
    assert mcp_status(api, first["access_token"]) == 401
    reused = api.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": first["refresh_token"],
            "client_id": client_id,
        },
    )
    assert reused.status_code == 400


def test_an_access_token_expires_after_an_hour(api, engine):
    _, tokens = signed_in_tokens(api, engine)
    assert mcp_status(api, tokens["access_token"]) == 200
    with session_scope(engine) as db:
        row = db.scalar(select(AccessToken))
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert mcp_status(api, tokens["access_token"]) == 401


def test_revoking_in_settings_ends_the_access_and_refresh_tokens(api, engine):
    client_id, tokens = signed_in_tokens(api, engine)
    boss = signed_in(api, engine, "boss@example.com")
    grant = api.get("/me/tokens", headers=boss).json()[0]
    assert api.delete(f"/me/tokens/{grant['id']}", headers=boss).status_code == 204
    assert mcp_status(api, tokens["access_token"]) == 401
    refresh = api.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": client_id,
        },
    )
    assert refresh.status_code == 400


def test_the_assistant_can_revoke_its_own_sign_in(api, engine):
    client_id, tokens = signed_in_tokens(api, engine)
    # The SDK's revoke form needs a client_secret field even for a public client; empty is fine.
    form = {"token": tokens["refresh_token"], "client_id": client_id, "client_secret": ""}
    done = api.post("/revoke", data=form)
    assert done.status_code == 200, done.text
    assert mcp_status(api, tokens["access_token"]) == 401


def test_signing_in_again_replaces_the_last_connection_of_that_assistant(api, engine):
    with session_scope(engine) as db:
        boss = db.scalar(select(User).where(User.email == "boss@example.com"))
    client_id = register(api)
    for _ in range(2):
        verifier, challenge = pkce()
        rid = request_id(start(api, client_id, challenge))
        got = code_of(allow(api, signed_in(api, engine, "boss@example.com"), rid))
        last = exchange(api, client_id, got["code"], verifier).json()
    with session_scope(engine) as db:
        rows = db.scalars(select(AccessToken).where(AccessToken.user_id == boss.id)).all()
        assert sorted(r.revoked_at is None for r in rows) == [False, True]
    assert mcp_status(api, last["access_token"]) == 200


def test_signed_in_connections_do_not_use_up_the_pasted_token_limit(api, engine):
    signed_in_tokens(api, engine)
    boss = signed_in(api, engine, "boss@example.com")
    for i in range(5):
        assert api.post("/me/tokens", headers=boss, json={"name": f"t{i}"}).status_code == 201


def test_registering_is_capped_an_hour(api, engine, monkeypatch):
    monkeypatch.setattr(oauth, "REGISTRATIONS_PER_HOUR", 2)
    register(api, "a")
    register(api, "b")
    third = api.post(
        "/register",
        json={
            "client_name": "c",
            "redirect_uris": [REDIRECT],
            "token_endpoint_auth_method": "none",
        },
    )
    assert third.status_code == 400
    with session_scope(engine) as db:
        assert len(db.scalars(select(OAuthClient)).all()) == 2


def test_the_name_an_assistant_gives_itself_is_shortened_and_never_trusted():
    assert oauth.client_name({"client_name": "x" * 80}) == "x" * 40
    assert oauth.client_name({}) == "An assistant"
    assert oauth.client_name({"client_name": "   "}) == "An assistant"


def test_sign_in_is_off_rather_than_crashing_on_a_plain_http_address(engine):
    from app.harness.server import oauth_routes

    assert oauth_routes(lambda: session_scope(engine), "http://192.168.1.20:8000", "x") == []
    assert oauth_routes(lambda: session_scope(engine), "http://localhost:8000", "x")
    assert oauth_routes(lambda: session_scope(engine), "https://api.example", "x")
