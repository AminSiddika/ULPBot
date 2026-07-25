from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str
    owner_id: int
    admin_ids: str = ""

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "ulpbot"

    redis_url: str = "redis://localhost:6379/0"

    webhook_host: str = ""
    webhook_path: str = "/webhook"
    webhook_port: int = 8080

    sentry_dsn: str = ""

    data_dir: str = "./data"
    downloads_dir: str = "./downloads"

    log_level: str = "INFO"

    @property
    def admin_ids_set(self) -> set[int]:
        return {int(x.strip()) for x in self.admin_ids.split(",") if x.strip()}

    @property
    def webhook_url(self) -> str:
        return f"{self.webhook_host.rstrip('/')}{self.webhook_path}" if self.webhook_host else ""

    @property
    def use_webhook(self) -> bool:
        return bool(self.webhook_host)


settings = Settings()

Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
Path(settings.downloads_dir).mkdir(parents=True, exist_ok=True)
