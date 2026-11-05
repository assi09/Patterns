"""Central configuration, loaded from environment variables or a local `.env` file."""

from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FA_", extra="ignore")

    data_dir: Path = Path("data")
    export_dir: Path = Path("data/raw")  # an extracted Google Takeout export
    timezone: str = "UTC"
    # Browser origins allowed to call the API (the Expo web build). Native apps do not need CORS.
    cors_origins: list[str] = ["http://localhost:8081"]
    # Google Health API: an OAuth client of type "Desktop app" and where its refresh token is kept.
    google_client_id: SecretStr | None = None
    google_client_secret: SecretStr | None = None
    google_token_file: Path = Path("data/google_token.json")
    # Connecting Google Health from the app: the key that encrypts stored tokens (Fernet), this
    # server's address for Google's callback, and the app's address to send the browser back to.
    token_key: SecretStr | None = None
    public_url: str = "http://127.0.0.1:8000"
    app_url: str = "http://localhost:8081"
    # Send due reminders from a loop inside the API, once a minute.
    reminders_enabled: bool = True
    # Have the owning expert explain each smart alarm (one quick run each); off: the template.
    alarm_explanations: bool = True
    # Opt-in only after the confirmed-action path and Google write scopes are configured.
    google_writes_enabled: bool = False
    # The database: Postgres from docker-compose.yml locally, a managed Postgres when deployed.
    database_url: str = (
        "postgresql+psycopg://fitbit_agent:local-dev-only@localhost:5433/fitbit_agent"
    )

    # The agent's language model: a small model for tool loops, a large one for write-ups.
    openai_api_key: SecretStr | None = None
    openai_small_model: str = "gpt-5.4-mini"
    openai_large_model: str = "gpt-5.5"
    # The router: TypeSafe's Jev, given the question text only.
    typesafe_api_key: SecretStr | None = None
    fdc_api_key: SecretStr | None = None  # USDA FoodData Central; without it, no food lookups
    typesafe_model: str = "jev-latest"
    typesafe_base_url: str = "https://api.typesafe.ai"
    # Accounts: who may approve sign-ups, and how long a device stays signed in.
    admin_emails: list[str] = []
    session_days: int = 30
    # Questions from the app: daily spending caps (US dollars, from stored answer costs, per local
    # day) and how long a request waits for the answer before telling the app to check back.
    chat_daily_cap_per_user_usd: float = 0.10
    chat_daily_cap_total_usd: float = 0.50
    chat_wait_s: float = 55.0
    # Hard cap on model spending by this process, in US dollars.
    llm_spend_cap_usd: float = 20.0
    # Team reports: whether a model writes the weekly narrative (templated text otherwise), and
    # the most one report's text may cost.
    team_report_narrative: bool = False
    team_report_cap_usd: float = 0.02
    # Team report emails: written to data/outbox/ unless sending through Resend is turned on,
    # with its key and a sender Resend accepts (onboarding@resend.dev only reaches the account's
    # own address; any other needs a verified domain).
    email_backend: Literal["outbox", "resend"] = "outbox"
    email_api_key: SecretStr | None = None
    email_from: str = "Patterns <onboarding@resend.dev>"

    @field_validator("database_url")
    @classmethod
    def _psycopg(cls, url: str) -> str:
        # Hosts such as Railway give postgres:// or postgresql://; SQLAlchemy needs the driver.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url.removeprefix(prefix)
        return url


settings = Settings()
