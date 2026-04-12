from __future__ import annotations

from authlib.integrations.starlette_client import OAuth

from threadgram.config import Settings


def build_oauth_client(settings: Settings) -> OAuth | None:
    if not settings.github_client_id or not settings.github_client_secret:
        return None

    oauth = OAuth()
    oauth.register(
        name="github",
        client_id=settings.github_client_id,
        client_secret=settings.github_client_secret,
        access_token_url="https://github.com/login/oauth/access_token",
        authorize_url="https://github.com/login/oauth/authorize",
        api_base_url="https://api.github.com/",
        client_kwargs={"scope": settings.github_scope},
    )
    return oauth
