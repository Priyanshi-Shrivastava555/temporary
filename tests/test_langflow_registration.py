import json
from pathlib import Path

from scripts.register_langflow_flow import (
    _choose_canonical,
    _flow_signature,
    _matching_flows,
    _update_flow,
    adapt_flow_for_catalog,
)


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code
        self.ok = status_code < 400
        self.request = type("Request", (), {"method": "PATCH"})()
        self.url = "http://langflow.test/api/v1/flows/flow-id"
        self.text = ""

    def json(self):
        return {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected HTTP {self.status_code}")


class FakeSession:
    def __init__(self, statuses):
        self.statuses = iter(statuses)
        self.methods = []

    def request(self, method, _url, **_kwargs):
        self.methods.append(method)
        return FakeResponse(next(self.statuses))


def test_flow_signature_ignores_server_metadata():
    desired = {"data": {"nodes": [{"id": "a", "data": {"type": "Agent"}}], "edges": []}}
    existing = {"updated_at": "server value", **desired}

    assert _flow_signature(existing) == _flow_signature(desired)


def test_flow_signature_detects_executable_component_change():
    desired = {
        "data": {
            "nodes": [{
                "id": "model",
                "data": {"type": "ShopBuddyModel", "node": {
                    "template": {"code": {"value": "new source"}},
                    "outputs": [{"name": "model"}],
                }},
            }],
            "edges": [],
        }
    }
    existing = {
        "data": {
            "nodes": [{
                "id": "model",
                "data": {"type": "ShopBuddyModel", "node": {
                    "template": {"code": {"value": "old source"}},
                    "outputs": [{"name": "model"}],
                }},
            }],
            "edges": [],
        }
    }

    assert _flow_signature(existing) != _flow_signature(desired)


def test_flow_signature_ignores_deployment_local_model_configuration():
    desired = {
        "data": {
            "nodes": [{
                "id": "model",
                "data": {"type": "ext:shop_buddy:ShopBuddyModelComponent@extra", "node": {
                    "template": {
                        "openai_api_key": {"value": ""},
                        "openai_base_url": {"value": ""},
                        "openai_model": {"value": "gpt-4o-mini"},
                    },
                    "outputs": [{"name": "model"}],
                }},
            }],
            "edges": [],
        }
    }
    live = {
        "data": {
            "nodes": [{
                "id": "model",
                "data": {"type": "ext:shop_buddy:ShopBuddyModelComponent@extra", "node": {
                    "template": {
                        "openai_api_key": {"value": "server-secret"},
                        "openai_base_url": {"value": "https://proxy.example/v1"},
                        "openai_model": {"value": "gpt-4o-mini"},
                    },
                    "outputs": [{"name": "model"}],
                }},
            }],
            "edges": [],
        }
    }

    assert _flow_signature(live) == _flow_signature(desired)


def test_flow_signature_detects_evaluator_name_change():
    data = {"nodes": [], "edges": []}

    assert _flow_signature({"name": "Shop Buddy", "data": data}) != _flow_signature(
        {"name": "Shop_Buddy", "data": data}
    )


def test_duplicate_selection_prefers_evaluator_named_flow_and_ignores_archive():
    desired = {"id": "export-id", "name": "Shop_Buddy", "endpoint_name": "shop-buddy"}
    flows = [
        {"id": "export-id", "name": "Shop_Buddy_legacy_export", "endpoint_name": None},
        {"id": "old-id", "name": "Shop Buddy", "endpoint_name": "shop-buddy"},
        {"id": "canonical-id", "name": "Shop_Buddy", "endpoint_name": "shop-buddy"},
    ]

    matches = _matching_flows(flows, desired)

    assert {item["id"] for item in matches} == {"old-id", "canonical-id"}
    assert _choose_canonical(matches, desired)["id"] == "canonical-id"


def test_flow_update_falls_back_from_patch_to_put():
    session = FakeSession([405, 200])

    response = _update_flow(session, "flow-id", {"name": "Shop Buddy"})

    assert response.status_code == 200
    assert session.methods == ["patch", "put"]


def test_flow_update_uses_patch_when_supported():
    session = FakeSession([200])

    response = _update_flow(session, "flow-id", {"name": "Shop Buddy"})

    assert response.status_code == 200
    assert session.methods == ["patch"]


def test_export_uses_evaluator_name_and_external_model_mode():
    flow_path = Path(__file__).resolve().parents[1] / "langflow" / "shop_buddy.flow.json"
    flow = json.loads(flow_path.read_text(encoding="utf-8"))

    assert flow["name"] == "Shop_Buddy"
    assert flow["endpoint_name"] == "shop-buddy"
    assert flow["description"].endswith("Registration schema v3.")
    agents = [node for node in flow["data"]["nodes"] if node["data"]["type"] == "Agent"]
    assert len(agents) == 3
    assert all(agent["data"].get("_connectionMode") is True for agent in agents)
    assert all(agent["data"]["node"]["template"]["model"]["type"] == "other" for agent in agents)
    model_edges = [
        edge for edge in flow["data"]["edges"]
        if edge["data"]["targetHandle"].get("fieldName") == "model"
    ]
    assert len(model_edges) == 3
    assert all(edge["data"]["targetHandle"]["type"] == "other" for edge in model_edges)
    model_edges = [
        edge for edge in flow["data"]["edges"]
        if edge["data"]["targetHandle"].get("fieldName") == "model"
    ]
    assert len(model_edges) == 3
    assert all(edge["data"]["targetHandle"]["inputTypes"] == ["LanguageModel"] for edge in model_edges)


def test_export_uses_distinct_labels_for_all_five_custom_tools():
    flow_path = Path(__file__).resolve().parents[1] / "langflow" / "shop_buddy.flow.json"
    flow = json.loads(flow_path.read_text(encoding="utf-8"))
    tool_nodes = {
        node["data"]["type"]: node["data"]["display_name"]
        for node in flow["data"]["nodes"]
        if str(node["data"].get("type", "")).startswith("ext:shop_buddy:")
        and node["data"]["type"] != "ext:shop_buddy:ShopBuddyModelComponent@extra"
    }

    assert tool_nodes == {
        "ext:shop_buddy:SearchProductsComponent@extra": "Search Products",
        "ext:shop_buddy:AddProductToCartComponent@extra": "AddProductToCart",
        "ext:shop_buddy:UpdateCartItemComponent@extra": "UpdateCartItem",
        "ext:shop_buddy:DeleteCartItemComponent@extra": "DeleteCartItem",
        "ext:shop_buddy:GetCartItemsComponent@extra": "GetCartItems",
    }


def test_vdi_catalog_adapter_rebases_builtins_and_model_edges():
    flow = {
        "data": {
            "nodes": [
                {
                    "id": "input",
                    "data": {"type": "ChatInput", "display_name": "Input", "node": {
                        "display_name": "Input",
                        "template": {"input_value": {"value": "saved input"}, "code": {"value": "from lfx"}},
                    }},
                },
                {
                    "id": "agent",
                    "data": {"type": "Agent", "display_name": "Orchestrator", "node": {
                        "display_name": "Orchestrator",
                        "template": {
                            "model": {"value": "", "type": "other"},
                            "system_prompt": {"value": "saved prompt"},
                            "code": {"value": "from lfx"},
                        },
                    }},
                },
            ],
            "edges": [{
                "target": "agent",
                "targetHandle": "{œfieldNameœ: œmodelœ, œtypeœ: œotherœ}",
                "data": {"targetHandle": {"fieldName": "model", "inputTypes": ["LanguageModel"], "type": "other"}},
            }],
        }
    }
    catalog = {
        "inputs": {"ChatInput": {"display_name": "Chat Input", "template": {
            "input_value": {"value": ""}, "code": {"value": "from langflow"},
        }}},
        "agents": {"Agent": {"display_name": "Agent", "template": {
            "agent_llm": {"value": "OpenAI", "input_types": [], "type": "str"},
            "system_prompt": {"value": "native prompt"},
            "add_current_date_tool": {"value": False},
            "code": {"value": "from langflow"},
        }}},
    }

    adapted = adapt_flow_for_catalog(flow, catalog)
    input_node, agent = adapted["data"]["nodes"]
    edge = adapted["data"]["edges"][0]

    assert input_node["data"]["node"]["template"]["input_value"]["value"] == "saved input"
    assert input_node["data"]["node"]["template"]["code"]["value"] == "from langflow"
    assert agent["data"]["node"]["template"]["system_prompt"]["value"] == "saved prompt"
    assert agent["data"]["node"]["template"]["code"]["value"] == "from langflow"
    assert agent["data"]["node"]["template"]["agent_llm"]["value"] == "Custom"
    assert agent["data"]["node"]["template"]["agent_llm"]["input_types"] == ["LanguageModel"]
    assert edge["data"]["targetHandle"] == {
        "fieldName": "agent_llm", "inputTypes": ["LanguageModel"], "type": "str",
    }
    assert "œfieldNameœ: œagent_llmœ" in edge["targetHandle"]
    assert "œtypeœ: œstrœ" in edge["targetHandle"]
