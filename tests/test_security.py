from threadgram.security import extract_agent_key_prefix, generate_agent_key, verify_agent_key


def test_generated_agent_key_round_trip():
    prefix, key_hash, full_key = generate_agent_key()

    assert full_key.startswith(f"amk_{prefix}_")
    assert extract_agent_key_prefix(full_key) == prefix
    assert verify_agent_key(full_key, key_hash)
    assert not verify_agent_key(f"{full_key}x", key_hash)
