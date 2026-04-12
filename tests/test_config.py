from __future__ import annotations

from pathlib import Path

from agentgram.config import Settings


def test_cors_origins_accepts_comma_separated_env_file(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "AGENTGRAM_FRONTEND_ORIGIN=http://localhost:4173",
                "AGENTGRAM_CORS_ORIGINS=http://localhost:4173,http://localhost:8000",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.cors_origins == ["http://localhost:4173", "http://localhost:8000"]
    assert settings.effective_cors_origins == ["http://localhost:4173", "http://localhost:8000"]
