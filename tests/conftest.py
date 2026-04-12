from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from asgi_lifespan import LifespanManager

from agentgram.app import create_app
from agentgram.config import Settings


@pytest.fixture
async def app(tmp_path: Path):
    settings = Settings(
        testing=True,
        local_mode=False,
        auto_create_schema=True,
        secret_key="test-secret",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'agentgram.db'}",
        frontend_origin="http://localhost:4173",
        public_api_base_url="http://testserver",
        cors_origins=["http://localhost:4173"],
        session_same_site="lax",
        session_https_only=False,
    )
    application = create_app(settings)
    async with LifespanManager(application):
        yield application


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client
