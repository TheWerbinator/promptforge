"""Bootstrap smoke: the app boots, /health answers, the DSN normalizer works.

`promptforge_ragent.main` builds `app = create_app()` at import, which reads
settings — so it's imported *inside* the tests, after `base_env` sets the env.
"""

import pytest
from httpx import ASGITransport, AsyncClient


async def test_health_ok(base_env: None) -> None:
    from promptforge_ragent import __version__
    from promptforge_ragent.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": __version__}
    # The request-context middleware echoes the id even on simple responses.
    assert resp.headers["x-request-id"]


@pytest.mark.parametrize(
    "raw",
    [
        "postgresql://u:p@host/db",
        "postgres://u:p@host/db",
        "postgresql+asyncpg://u:p@host/db",
    ],
)
def test_dsn_normalizer_yields_asyncpg(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    from promptforge_ragent.core.config import Settings, get_settings

    monkeypatch.setenv("PF_DATABASE_URL", raw)
    monkeypatch.setenv("PF_JWT_SECRET", "a" * 48)
    get_settings.cache_clear()
    assert Settings().async_database_url().startswith("postgresql+asyncpg://")


def test_dsn_normalizer_rewrites_sslmode(monkeypatch: pytest.MonkeyPatch) -> None:
    from promptforge_ragent.core.config import Settings, get_settings

    monkeypatch.setenv("PF_DATABASE_URL", "postgresql://u:p@host/db?sslmode=require")
    monkeypatch.setenv("PF_JWT_SECRET", "a" * 48)
    get_settings.cache_clear()
    dsn = Settings().async_database_url()
    assert "ssl=require" in dsn
    assert "sslmode=" not in dsn
