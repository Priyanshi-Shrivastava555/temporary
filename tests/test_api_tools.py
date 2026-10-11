from fastapi.testclient import TestClient

from shop_buddy.api import create_app


def test_all_five_required_tool_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOP_BUDDY_DB_PATH", str(tmp_path / "tools.db"))
    client = TestClient(create_app())
    session_id = "api-tool-shopper"

    searched = client.get("/search_products/", params={"query": "conference chairs"})
    assert searched.status_code == 200
    product = searched.json()["products"][0]

    added = client.post("/add_product_to_cart/", json={
        "product_id": product["id"], "quantity": 2, "session_id": session_id
    })
    assert added.status_code == 200
    assert added.json()["cart"]["item_count"] == 2

    retrieved = client.get("/get_cart_items/", params={"session_id": session_id})
    assert retrieved.status_code == 200
    assert retrieved.json()["items"][0]["product_id"] == product["id"]

    updated = client.put("/update_product_in_cart/", json={
        "product_id": product["id"], "quantity": 3, "session_id": session_id
    })
    assert updated.status_code == 200
    assert updated.json()["cart"]["item_count"] == 3

    deleted = client.request("DELETE", "/delete_product_from_cart/", json={
        "product_id": product["id"], "session_id": session_id
    })
    assert deleted.status_code == 200
    assert deleted.json()["cart"]["items"] == []


def test_health_reports_real_framework_installation(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOP_BUDDY_DB_PATH", str(tmp_path / "health.db"))
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["frameworks"]["langgraph"] is True
    assert body["frameworks"]["crewai"] is True
    assert body["frameworks"]["autogen"] is True


def test_launcher_workflow_override_wins_without_rewriting_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOP_BUDDY_DB_PATH", str(tmp_path / "phase.db"))
    monkeypatch.setenv("WORKFLOW_MODE", "langgraph")
    monkeypatch.setenv("SHOP_BUDDY_WORKFLOW_OVERRIDE", "crewai")

    body = TestClient(create_app()).get("/health").json()

    assert body["workflow"] == "crewai"

