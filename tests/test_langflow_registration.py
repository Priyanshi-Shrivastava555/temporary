import json
from pathlib import Path

from scripts.register_langflow_flow import _flow_signature, _update_flow


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


def test_flow_signature_detects_evaluator_name_change():
    data = {"nodes": [], "edges": []}

    assert _flow_signature({"name": "Shop Buddy", "data": data}) != _flow_signature(
        {"name": "Shop_Buddy", "data": data}
    )


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
    agents = [node for node in flow["data"]["nodes"] if node["data"]["type"] == "Agent"]
    assert len(agents) == 3
    assert all(agent["data"].get("_connectionMode") is True for agent in agents)
    model_edges = [
        edge for edge in flow["data"]["edges"]
        if edge["data"]["targetHandle"].get("fieldName") == "model"
    ]
    assert len(model_edges) == 3
    assert all(edge["data"]["targetHandle"]["inputTypes"] == ["LanguageModel"] for edge in model_edges)
