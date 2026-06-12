from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Anthropic
    ANTHROPIC_API_KEY: str = ""

    # Robinhood MCP
    ROBINHOOD_MCP_URL: str = "https://agent.robinhood.com/mcp/trading"

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

    # App
    DEPLOYMENT_MODE: str = "local"
    AGENT_INTERVAL_MINUTES: int = 15
    MIN_WALLET_BALANCE_USD: float = 10.0
    PORT: int = 8000

settings = Settings()
