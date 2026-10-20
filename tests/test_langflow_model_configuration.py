from scripts.configure_langflow_model import MODEL_COMPONENT_TYPE, apply_openai_configuration


def test_openai_configuration_updates_only_the_shop_buddy_model() -> None:
    flow = {
        "data": {
            "nodes": [
                {"data": {"type": "Agent", "node": {"template": {"model": {"value": "unchanged"}}}}},
                {
                    "data": {
                        "type": MODEL_COMPONENT_TYPE,
                        "node": {
                            "template": {
                                "openai_api_key": {"value": ""},
                                "openai_base_url": {"value": ""},
                                "openai_model": {"value": "gpt-4o-mini"},
                            }
                        },
                    }
                },
            ]
        }
    }

    configured = apply_openai_configuration(
        flow,
        api_key="test-key",
        base_url="https://proxy.example/v1",
        model="gpt-4o-mini",
    )

    model = configured["data"]["nodes"][1]["data"]["node"]["template"]
    assert model["openai_api_key"]["value"] == "test-key"
    assert model["openai_base_url"]["value"] == "https://proxy.example/v1"
    assert flow["data"]["nodes"][1]["data"]["node"]["template"]["openai_api_key"]["value"] == ""


def test_openai_configuration_requires_the_shop_buddy_model() -> None:
    try:
        apply_openai_configuration(
            {"data": {"nodes": []}},
            api_key="key",
            base_url="https://proxy.example/v1",
            model="model",
        )
    except RuntimeError as exc:
        assert "Shop Buddy model" in str(exc)
    else:
        raise AssertionError("Expected a missing-model error")
