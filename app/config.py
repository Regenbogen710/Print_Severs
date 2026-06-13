import configparser
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


CONFIG_FILE = Path("config.ini")

CONFIG_KEY_MAP = {
    "server": {
        "host": "host",
        "port": "port",
        "worker_enabled": "worker_enabled",
    },
    "printer": {
        "printer_name": "printer_name",
        "dry_run": "dry_run",
        "sumatra_pdf_path": "sumatra_pdf_path",
        "libreoffice_path": "libreoffice_path",
    },
    "storage": {
        "data_dir": "data_dir",
        "max_upload_mb": "max_upload_mb",
        "allowed_extensions": "allowed_extensions",
    },
    "access": {
        "public_access_enabled": "public_access_enabled",
        "public_ip_whitelist": "public_ip_whitelist",
        "trust_proxy_headers": "trust_proxy_headers",
        "trusted_proxy_ips": "trusted_proxy_ips",
    },
    "auth": {
        "admin_username": "admin_username",
        "admin_password": "admin_password",
        "require_auth_for_upload": "require_auth_for_upload",
    },
    "print": {
        "print_command_timeout_seconds": "print_command_timeout_seconds",
        "worker_poll_seconds": "worker_poll_seconds",
    },
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="PRINT_SERVER_",
        extra="ignore",
    )

    app_name: str = "PrintSevers"
    app_version: str = "0.1.0"

    host: str = "0.0.0.0"
    port: int = 8000
    worker_enabled: bool = True

    printer_name: str = "Lenovo LJ2205"
    dry_run: bool = False
    sumatra_pdf_path: str | None = None
    libreoffice_path: str | None = None
    print_command_timeout_seconds: int = 90
    worker_poll_seconds: float = 2.0

    data_dir: Path = Path("data")
    max_upload_mb: int = Field(default=50, ge=1, le=512)
    allowed_extensions: list[str] = [
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".bmp",
        ".gif",
        ".tif",
        ".tiff",
        ".doc",
        ".docx",
        ".rtf",
        ".txt",
    ]

    public_access_enabled: bool = False
    public_ip_whitelist: list[str] = []
    trust_proxy_headers: bool = False
    trusted_proxy_ips: list[str] = []

    admin_username: str = "admin"
    admin_password: str = "change-this-password"
    require_auth_for_upload: bool = False

    @field_validator("allowed_extensions", "public_ip_whitelist", "trusted_proxy_ips", mode="before")
    @classmethod
    def parse_csv_list(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return value
        return list(value)

    @field_validator("allowed_extensions")
    @classmethod
    def normalize_extensions(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            ext = item.strip().lower()
            if not ext:
                continue
            if not ext.startswith("."):
                ext = f".{ext}"
            normalized.append(ext)
        return sorted(set(normalized))

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "queue.sqlite3"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def log_file(self) -> Path:
        return self.log_dir / "print-server.log"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings(**load_config_file(CONFIG_FILE))
    settings.ensure_directories()
    return settings


def load_config_file(path: Path = CONFIG_FILE) -> dict[str, Any]:
    if not path.exists():
        return {}

    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")

    values: dict[str, Any] = {}
    for section, key_map in CONFIG_KEY_MAP.items():
        if not parser.has_section(section):
            continue
        for config_key, settings_key in key_map.items():
            if not parser.has_option(section, config_key):
                continue
            values[settings_key] = parser.get(section, config_key)
    return values
