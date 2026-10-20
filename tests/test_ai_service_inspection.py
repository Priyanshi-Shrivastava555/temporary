from scripts.inspect_existing_ai_services import (
    component_summary,
    flow_records,
    flow_size,
    format_environment,
    openapi_paths,
    redact_command,
    safe_url,
)


def test_report_helpers_redact_secrets_and_url_credentials() -> None:
    secret = "super-secret-value"
    lines = format_environment(
        {
            "LANGFLOW_API_KEY": secret,
            "OPENAI_BASE_URL": "https://user:password@example.test/v1?token=secret",
        }
    )

    rendered = "\n".join(lines)
    assert secret not in rendered
    assert "password" not in rendered
    assert "token=secret" not in rendered
    assert "https://example.test/v1" in rendered


def test_command_redaction_handles_common_secret_arguments() -> None:
    command = "langflow run --api-key secret123 password=hunter2"

    redacted = redact_command(command)

    assert "secret123" not in redacted
    assert "hunter2" not in redacted
    assert redacted.count("<redacted>") == 2


def test_flow_and_openapi_summaries_tolerate_langflow_shapes() -> None:
    flow = {
        "name": "Shop_Buddy",
        "data": {"nodes": [{}, {}], "edges": [{}]},
    }
    assert flow_records({"items": [flow]}) == [flow]
    assert flow_size(flow) == (2, 1)
    assert openapi_paths({"paths": {"/api/v1/run/{flow_id}": {}, "/health": {}}}) == [
        "/api/v1/run/{flow_id}",
        "/health",
    ]


def test_component_summary_reports_categories_without_dumping_payload() -> None:
    count, categories = component_summary(
        {"agents": [{}, {}], "tools": {"Search": {}, "Cart": {}}, "metadata": "ignored"}
    )

    assert count == 4
    assert categories == ["agents", "tools"]


def test_safe_url_handles_non_url_values() -> None:
    assert safe_url("not-a-url") == "configured"
