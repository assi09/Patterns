"""The switch that hides the individual side (app/api/features.py, docs/pivot.md)."""

import pytest
from fastapi.testclient import TestClient
from test_auth import PASSWORD, client, clock, engine  # noqa: F401 (fixtures)

from app.api.main import create_app
from app.config import Settings, settings

# One route of each part that is turned off; each needs a sign-in when on.
PERSONAL = [
    ("get", "/chat"),
    ("post", "/chat"),
    ("get", "/conversations"),
    ("get", "/actions"),
    ("get", "/memory"),
    ("get", "/alarms"),
    ("get", "/alarm-settings"),
    ("get", "/reminders"),
    ("post", "/reminders"),
    ("get", "/reports/latest"),
]
# What the team product still needs: these must answer with the switch off.
KEPT = [("get", "/data/status"), ("get", "/days/latest"), ("get", "/notifications")]


def test_off_by_default():
    assert Settings().personal_features is False


@pytest.mark.parametrize(("method", "path"), PERSONAL)
def test_personal_routes_are_missing_when_off(monkeypatch, method, path):
    monkeypatch.setattr(settings, "personal_features", False)
    response = getattr(TestClient(create_app()), method)(path)
    # Checked before the sign-in, so the server does not even say the route exists.
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(("method", "path"), PERSONAL)
def test_personal_routes_work_when_on(method, path):
    response = getattr(TestClient(create_app()), method)(path)
    assert response.status_code == 401  # as before the switch: a sign-in is needed


@pytest.mark.parametrize(("method", "path"), KEPT)
def test_team_product_routes_stay(monkeypatch, method, path):
    monkeypatch.setattr(settings, "personal_features", False)
    response = getattr(TestClient(create_app()), method)(path)
    assert response.status_code == 401  # there, and asking for a sign-in


@pytest.mark.parametrize("on", [True, False])
def test_account_tells_the_app(client, monkeypatch, on):  # noqa: F811
    monkeypatch.setattr(settings, "personal_features", on)
    response = client.post("/auth/signup", json={"email": "a@example.com", "password": PASSWORD})
    assert response.status_code == 201
    token = response.json()["token"]
    assert response.json()["account"]["personalFeatures"] is on
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["personalFeatures"] is on
