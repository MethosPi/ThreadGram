from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from threadgram.api.router import build_api_router
from threadgram.auth import build_oauth_client
from threadgram.config import Settings, get_settings
from threadgram.db import create_all, create_engine, create_session_factory
from threadgram.mcp_app import MCPAgentAuthApp, create_mcp_server


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    oauth = build_oauth_client(settings)
    mcp = create_mcp_server(session_factory, settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.auto_create_schema:
            await create_all(engine)
        async with mcp.session_manager.run():
            yield
        await engine.dispose()

    app = FastAPI(title=settings.app_name, lifespan=lifespan, redirect_slashes=False)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.oauth = oauth

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie=settings.session_cookie_name,
        same_site=settings.session_same_site,
        https_only=settings.session_https_only,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.effective_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Mcp-Session-Id"],
    )

    app.include_router(build_api_router())
    app.mount("/", MCPAgentAuthApp(mcp.streamable_http_app(), session_factory))
    return app
