from pathlib import Path

from pytest import MonkeyPatch

from app.config import Settings, load_config_file


def test_load_config_file_overrides_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.ini"
    config_path.write_text(
        """
[server]
host = 127.0.0.1
port = 8123
worker_enabled = false

[printer]
printer_name = Test Printer
dry_run = true

[storage]
data_dir = custom-data
max_upload_mb = 12
allowed_extensions = .pdf,.png

[access]
public_access_enabled = true
public_ip_whitelist = 203.0.113.10,198.51.100.0/24

[auth]
admin_username = root
admin_password = changed
require_auth_for_upload = true
""".strip(),
        encoding="utf-8",
    )

    values = load_config_file(config_path)
    settings = Settings(**values)

    assert settings.host == "127.0.0.1"
    assert settings.port == 8123
    assert not settings.worker_enabled
    assert settings.printer_name == "Test Printer"
    assert settings.dry_run
    assert settings.data_dir == Path("custom-data")
    assert settings.max_upload_mb == 12
    assert settings.allowed_extensions == [".pdf", ".png"]
    assert settings.public_access_enabled
    assert settings.public_ip_whitelist == ["203.0.113.10", "198.51.100.0/24"]
    assert settings.admin_username == "root"
    assert settings.admin_password == "changed"
    assert settings.require_auth_for_upload


def test_settings_ignores_legacy_dotenv(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("PRINT_SERVER_ADMIN_PASSWORD", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "PRINT_SERVER_ADMIN_PASSWORD=from-dotenv\n",
        encoding="utf-8",
    )

    settings = Settings()

    assert settings.admin_password == "change-this-password"
