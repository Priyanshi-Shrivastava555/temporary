"""Run the six Phase 1 acceptance queries against the live FastAPI service."""
from __future__ import annotations

import argparse
import uuid

import requests


QUERIES = [
    "Show me office chairs.",
    "Find an office chair under $500 and add it to my cart.",
    "Add 2 conference chairs to my cart.",
    "Change quantity to 3.",
    "Show my cart.",
    "Remove the conference chairs from my cart.",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    session_id = f"phase1-smoke-{uuid.uuid4()}"
    responses: list[dict] = []

    for query in QUERIES:
        response = requests.post(
            f"{base_url}/chat",
            json={"message": query, "session_id": session_id},
            timeout=90,
        )
        response.raise_for_status()
        payload = response.json()
        responses.append(payload)
        print(f"PASS: {query} -> {payload['intent']}")

    assert responses[0]["products"], "Office-chair search returned no products."
    assert responses[1]["intent"] == "combined" and responses[1]["cart"]["items"], "Combined search/add failed."
    conference = next(item for item in responses[2]["cart"]["items"] if "conference" in item["title"].lower())
    assert conference["quantity"] == 2, "Add quantity was not 2."
    conference = next(item for item in responses[3]["cart"]["items"] if "conference" in item["title"].lower())
    assert conference["quantity"] == 3, "Update quantity was not 3."
    assert any(result["tool"] == "GetCartItems" for result in responses[4]["tool_results"]), "View-cart tool did not run."
    assert not any("conference" in item["title"].lower() for item in responses[5]["cart"]["items"]), "Delete failed."

    # Remove any item added by the combined query so the smoke test leaves no cart data behind.
    for item in responses[5]["cart"]["items"]:
        cleanup = requests.delete(
            f"{base_url}/delete_product_from_cart/",
            json={"product_id": item["product_id"], "session_id": session_id},
            timeout=30,
        )
        cleanup.raise_for_status()
    print("Phase 1 acceptance smoke test passed all six queries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

