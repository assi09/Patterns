"""Seeds a throwaway database for `eval/mcp_red_team.py`: team A from PMData's real people, team B, HR, an
unapproved account and a demoted supervisor, each with a token. Prints nothing personal.

Usage, from the repository root, with a new SQLite file (never a real database):
    FA_DATABASE_URL=sqlite:////tmp/rt.db alembic -c backend/alembic.ini upgrade head
    PYTHONPATH=backend:eval python eval/mcp_red_team_seed.py sqlite:////tmp/rt.db /tmp/tokens.json
The tokens file is for that throwaway database only and stays out of git.
"""

import json
import sys
from datetime import UTC, datetime

import real_data
from app.auth.passwords import hash_password
from app.db.daily import save_daily
from app.db.models import User
from app.harness import tokens
from app.teams import memberships
from app.teams.reports import SOURCE
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

engine = create_engine(sys.argv[1])
joined = datetime(2019, 10, 1, tzinfo=UTC)
now = datetime.now(UTC)
pw = hash_password("rt-password-1")
with Session(engine) as db:

    def account(email, role, status="approved"):
        u = User(email=email, password_hash=pw, status=status, role=role)
        db.add(u)
        db.flush()
        return u

    boss_a = account("boss-a@example.com", "supervisor")
    boss_b = account("boss-b@example.com", "supervisor")
    demoted = account("demoted@example.com", "supervisor")
    hr = account("hr@example.com", "hr")
    pending = account("pending@example.com", "member", status="pending")
    team_a = memberships.create_team(db, boss_a, "Team A", None, joined)
    team_b = memberships.create_team(db, boss_b, "Team B", None, joined)
    team_d = memberships.create_team(db, demoted, "Team D", None, joined)
    team_a.hr_id = hr.id
    members = []
    for i, frame in enumerate(real_data.load_pmdata().values(), 1):
        m = account(f"pm-{i:02d}@example.com", "member")
        memberships.join(db, team_a, m, joined)
        save_daily(db, m.id, SOURCE, frame.dropna(how="all"))
        members.append(m)
    out = {"team_a": str(team_a.id), "team_b": str(team_b.id), "team_d": str(team_d.id)}
    for name, u in [
        ("boss_a", boss_a),
        ("boss_b", boss_b),
        ("demoted", demoted),
        ("hr", hr),
        ("member", members[0]),
        ("other_member", members[1]),
    ]:
        out[name] = tokens.make(db, u, "red team", now)[1]
        out[name + "_id"] = str(u.id)
    # A token made while approved, for an account then set back to pending.
    out["pending"] = tokens.make(db, pending, "red team", now)[1]
    revoked_row, out["revoked"] = tokens.make(db, boss_a, "to revoke", now)
    revoked_row.revoked_at = now
    demoted.role = "member"  # after the token was made
    db.commit()
with open(sys.argv[2], "w") as handle:
    json.dump(out, handle)
print("seeded: 2 supervisors, a demoted one, HR, a pending account, 16 real members")
