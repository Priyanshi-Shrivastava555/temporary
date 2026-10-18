from scripts.ensure_langflow_api_key import persist_env_key


def test_persist_env_key_adds_missing_value(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=test\n", encoding="utf-8")

    persist_env_key(env_file, "sk-langflow-test")

    assert env_file.read_text(encoding="utf-8") == (
        "OPENAI_API_KEY=test\n\nLANGFLOW_API_KEY=sk-langflow-test\n"
    )


def test_persist_env_key_replaces_duplicates_without_exposing_old_values(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LANGFLOW_API_KEY=old-one\nWORKFLOW_MODE=langgraph\nLANGFLOW_API_KEY=old-two\n",
        encoding="utf-8",
    )

    persist_env_key(env_file, "new-key")

    assert env_file.read_text(encoding="utf-8") == (
        "LANGFLOW_API_KEY=new-key\nWORKFLOW_MODE=langgraph\n"
    )
