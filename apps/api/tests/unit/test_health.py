"""Phase 1 smoke tests for /health and Settings loading."""

import pytest
from fastapi.testclient import TestClient

from promptforge_api import __version__
from promptforge_api.core.config import Settings, get_settings


@pytest.fixture
def client(base_env: None) -> TestClient:
    get_settings.cache_clear()
    from promptforge_api.main import create_app

    return TestClient(create_app())


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_openapi_spec_available(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "PromptForge API"


def test_settings_require_jwt_secret_min_length(
    base_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PF_JWT_SECRET", "too-short")
    with pytest.raises(ValueError, match=r"at least 32"):
        Settings()


def test_settings_missing_database_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PF_JWT_SECRET", "a" * 48)
    with pytest.raises(ValueError, match=r"database_url|DATABASE_URL"):
        Settings()
