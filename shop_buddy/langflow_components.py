"""HTTP callable versions of the five LangFlow custom tools.

Import these functions into LangFlow's custom-component skeleton and set the
API base URL to the running FastAPI server. They return structured JSON.
"""
from __future__ import annotations

import os
from typing import Any

import requests


def _base_url() -> str:
    return os.getenv("SHOP_BUDDY_API_URL", "http://127.0.0.1:8000").rstrip("/")


def search_products(query: str, max_price: float | None = None) -> dict[str, Any]:
    """Search UrbanNest products by natural-language keywords and optional price."""
    response = requests.get(f"{_base_url()}/search_products/", params={"query": query, "max_price": max_price}, timeout=15)
    response.raise_for_status()
    return response.json()


def add_product_to_cart(product_id: int, quantity: int = 1, session_id: str = "default") -> dict[str, Any]:
    """Add a catalogue product to the shopper's session cart."""
    response = requests.post(f"{_base_url()}/add_product_to_cart/", json={"product_id": product_id, "quantity": quantity, "session_id": session_id}, timeout=15)
    response.raise_for_status()
    return response.json()


def update_cart_item(product_id: int, quantity: int, session_id: str = "default") -> dict[str, Any]:
    """Set a cart product's quantity."""
    response = requests.put(f"{_base_url()}/update_product_in_cart/", json={"product_id": product_id, "quantity": quantity, "session_id": session_id}, timeout=15)
    response.raise_for_status()
    return response.json()


def delete_cart_item(product_id: int, session_id: str = "default") -> dict[str, Any]:
    """Remove a product from the shopper's cart."""
    response = requests.delete(f"{_base_url()}/delete_product_from_cart/", json={"product_id": product_id, "session_id": session_id}, timeout=15)
    response.raise_for_status()
    return response.json()


def get_cart_items(session_id: str = "default") -> dict[str, Any]:
    """Retrieve all cart items and their total."""
    response = requests.get(f"{_base_url()}/get_cart_items/", params={"session_id": session_id}, timeout=15)
    response.raise_for_status()
    return response.json()
