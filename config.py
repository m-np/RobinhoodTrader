from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Anthropic
    ANTHROPIC_API_KEY: str = ""

    # Robinhood MCP
    ROBINHOOD_MCP_URL: str = "https://agent.robinhood.com/mcp/trading"
    ROBINHOOD_CLIENT_ID: str = ""
    ROBINHOOD_CLIENT_SECRET: str = ""
    ROBINHOOD_REDIRECT_URI: str = (
        "http://localhost:8000/auth/robinhood/callback"
    )

    # Token encryption — generate once with:
    #   python -c "from cryptography.fernet import Fernet; \
    #              print(Fernet.generate_key().decode())"
    ENCRYPTION_KEY: str = ""

    # Database
    DATABASE_URL: str = "postgresql://localhost/trader"

    # Notifications
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""
    NOTIFY_TO_NUMBER: str = ""
    NOTIFY_EMAIL: str = ""

    # SMTP
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""

    # Stock discovery (Google search via Serper.dev — optional)
    # Get a free/paid key at https://serper.dev
    SERPER_API_KEY: str = ""

    # HTTP Basic Auth password for the dashboard (leave empty to disable)
    DASHBOARD_SECRET: str = ""

    # Timeouts (seconds)
    MCP_CALL_TIMEOUT: int = 30
    OAUTH_TIMEOUT: int = 15

    # App
    DEPLOYMENT_MODE: str = "local"
    AGENT_INTERVAL_MINUTES: int = 15
    MIN_WALLET_BALANCE_USD: float = 10.0
    PORT: int = 8000


settings = Settings()
