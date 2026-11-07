"""Runtime configuration for the web console."""

from __future__ import annotations

import os
import secrets
import typing as t
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_MAX_OUTPUT_CHARS = 200_000
DEFAULT_MAX_UPLOAD_BYTES = 64 * 1024 * 1024


def _abs(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _load_secret(path: Path) -> str:
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except OSError:
        existing = ""
    if existing:
        return existing
    value = secrets.token_hex(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(value, encoding="utf-8")
    except OSError:
        pass
    return value


@dataclass
class ServeConfig:
    """Everything the Flask app needs to run."""

    host: str = "127.0.0.1"
    port: int = 5000
    data_dir: str = ""
    db_path: str = ""
    upload_dir: str = ""
    secret_key: str = ""
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    admin_password: t.Optional[str] = None
    debug: bool = False
    open_browser: bool = False

    def ensure_dirs(self) -> None:
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        Path(self.upload_dir).mkdir(parents=True, exist_ok=True)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)


def build_config(
    *,
    host: str = "127.0.0.1",
    port: int = 5000,
    data_dir: t.Optional[str] = None,
    db_path: t.Optional[str] = None,
    secret_key: t.Optional[str] = None,
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    admin_password: t.Optional[str] = None,
    debug: bool = False,
    open_browser: bool = False,
) -> ServeConfig:
    data = _abs(data_dir or os.environ.get("CLIUI_DATA_DIR") or "data")
    upload = os.path.join(data, "uploads")
    db = _abs(db_path) if db_path else os.path.join(data, "cliui.sqlite3")
    if secret_key:
        key = secret_key
    else:
        key = os.environ.get("CLIUI_SECRET_KEY") or _load_secret(
            Path(data) / ".secret_key"
        )
    config = ServeConfig(
        host=host,
        port=port,
        data_dir=data,
        db_path=db,
        upload_dir=upload,
        secret_key=key,
        max_output_chars=max(1024, int(max_output_chars)),
        max_upload_bytes=max(1024, int(max_upload_bytes)),
        admin_password=admin_password or os.environ.get("CLIUI_ADMIN_PASSWORD"),
        debug=debug,
        open_browser=open_browser,
    )
    config.ensure_dirs()
    return config
