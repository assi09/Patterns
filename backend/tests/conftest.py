"""Shared test setup.

The individual side is off by default since the move to teams (app/api/features.py), but its
code is kept and must keep working, so its tests run with it on. Tests of the switch itself turn
it off again.
"""

import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def personal_features_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "personal_features", True)
