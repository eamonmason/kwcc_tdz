"""Application settings using pydantic-settings."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ZwiftPower authentication
    zwiftpower_username: str = ""
    zwiftpower_password: str = ""

    # AWS configuration
    aws_region: str = "eu-west-1"
    data_bucket: str = "kwcc-tdz-2026-data"
    website_bucket: str = "kwcc-tdz-2026-website"
    cloudfront_distribution_id: str = ""

    # Application paths
    riders_csv_path: str = "data/riders.csv"
    event_ids_path: str = "data/event_ids.json"
    output_path: str = "output"

    # Feature flags
    debug: bool = False
    dry_run: bool = False

    @property
    def riders_csv(self) -> Path:
        """Get riders CSV path as Path object."""
        return Path(self.riders_csv_path)

    @property
    def event_ids_file(self) -> Path:
        """Get event IDs JSON path as Path object."""
        return Path(self.event_ids_path)

    @property
    def output_dir(self) -> Path:
        """Get output directory as Path object."""
        return Path(self.output_path)


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
