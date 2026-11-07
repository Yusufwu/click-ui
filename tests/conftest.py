from __future__ import annotations

from pathlib import Path

import pytest

from cliui.config import build_config
from cliui.registry import load_app_entry
from cliui.storage.repo import Store
from cliui.web.server import create_app


FIXTURE_APPS = Path(__file__).parent / "fixtures" / "apps.py"


def _load(attr: str):
    return load_app_entry(f"{FIXTURE_APPS}:{attr}", str(FIXTURE_APPS.parent))


@pytest.fixture
def fixture_entry():
    return _load("fixture")


@pytest.fixture
def single_entry():
    return _load("single")


@pytest.fixture
def lazy_entry():
    return _load("lazy")


@pytest.fixture
def collection_entry():
    return _load("collection")


@pytest.fixture
def config(tmp_path):
    return build_config(
        data_dir=str(tmp_path / "data"),
        secret_key="test-secret-key",
        admin_password="adminpass",
    )


@pytest.fixture
def store(config):
    store = Store(config.db_path)
    created, password = store.ensure_admin(config.admin_password or "adminpass")
    assert created
    assert password == "adminpass"
    return store


@pytest.fixture
def web_app(fixture_entry, store, config):
    app = create_app(entries=[fixture_entry], store=store, config=config)
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def client(web_app):
    return web_app.test_client()


@pytest.fixture
def admin_client(client):
    response = client.post(
        "/login", data={"username": "admin", "password": "adminpass"}
    )
    assert response.status_code == 302
    return client


def login(client, username: str, password: str):
    return client.post("/login", data={"username": username, "password": password})
