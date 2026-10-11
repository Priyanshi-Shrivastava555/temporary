from fastapi.testclient import TestClient

from shop_buddy.api import create_app


def test_account_preferences_and_cart_are_bound_to_the_signed_in_user(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOP_BUDDY_DB_PATH", str(tmp_path / "account-test.db"))
    client = TestClient(create_app())

    registration = client.post("/auth/register", json={
        "name": "Morgan Shopper",
        "email": "morgan@example.com",
        "password": "a-secure-password",
    })
    assert registration.status_code == 200
    token = registration.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    saved = client.put("/preferences", headers=headers, json={
        "favorite_categories": ["Office Chairs"],
        "favorite_colors": ["Cognac"],
        "room": "Home office",
        "budget": 500,
    })
    assert saved.status_code == 200
    assert saved.json()["favorite_categories"] == ["Office Chairs"]

    # The account session deliberately overrides arbitrary browser session ids.
    added = client.post("/add_product_to_cart/", headers=headers, json={
        "product_id": 2, "quantity": 1, "session_id": "temporary-browser-session"
    })
    assert added.status_code == 200
    cart = client.get("/get_cart_items/", headers=headers, params={"session_id": "different-browser-session"})
    assert cart.json()["items"][0]["title"] == "Cedar Executive Chair"

    recommendations = client.get("/recommendations", headers=headers)
    assert recommendations.status_code == 200
    assert recommendations.json()["products"][0]["category"] == "Office Chairs"
