from __future__ import annotations

import hashlib
import secrets
from hmac import compare_digest


AGENT_KEY_PREFIX_BYTES = 5
AGENT_KEY_SECRET_BYTES = 24
AGENT_KEY_PREFIX = "amk"


def hash_agent_key(agent_key: str) -> str:
    return hashlib.sha256(agent_key.encode("utf-8")).hexdigest()


def generate_agent_key() -> tuple[str, str, str]:
    prefix = secrets.token_hex(AGENT_KEY_PREFIX_BYTES)
    secret = secrets.token_urlsafe(AGENT_KEY_SECRET_BYTES)
    full_key = f"{AGENT_KEY_PREFIX}_{prefix}_{secret}"
    return prefix, hash_agent_key(full_key), full_key


def extract_agent_key_prefix(agent_key: str) -> str | None:
    parts = agent_key.split("_", 2)
    if len(parts) != 3 or parts[0] != AGENT_KEY_PREFIX or not parts[1] or not parts[2]:
        return None
    return parts[1]


def verify_agent_key(agent_key: str, stored_hash: str) -> bool:
    return compare_digest(hash_agent_key(agent_key), stored_hash)
