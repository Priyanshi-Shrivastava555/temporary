"""Autonomous Shop Buddy workflow required by the Phase 3 assessment.

The module intentionally exposes the agents, registered backend functions,
``GroupChat``, manager, and ``autogen_run`` at module level because the lab
evaluator imports and inspects those definitions directly.
"""
from __future__ import annotations

import argparse
from contextvars import ContextVar
import json
import os
from pathlib import Path
import sys
from typing import Any
import uuid

import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# The activity explicitly requires the project .env to override inherited VDI
# values. Resolving it from this file also makes ``python -m`` independent of
# the shell's current working directory.
load_dotenv(PROJECT_ROOT / ".env", override=True)

# AutoGen 0.2 uses appdirs for optional runtime files. Keep any such files in
# the writable project directory; disk caching itself is disabled below.
runtime_data = PROJECT_ROOT / ".runtime-data"
runtime_data.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("XDG_DATA_HOME", str(runtime_data))
os.environ.setdefault("LOCALAPPDATA", str(runtime_data))

import autogen  # noqa: E402  (environment is configured before AutoGen import)


BACKEND_URL = os.getenv("SHOP_BUDDY_API_URL", "http://127.0.0.1:8000").rstrip("/")
REQUEST_TIMEOUT = 30
_active_session_id: ContextVar[str | None] = ContextVar("phase3_session_id", default=None)


def _session_id(supplied: str) -> str:
    """Use the run's shopper session even if an agent invents a default."""
    return _active_session_id.get() or supplied or "default"


def _json(response: requests.Response) -> dict[str, Any]:
    """Raise a useful HTTP error and return the backend JSON object."""
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise TypeError("The Shop Buddy backend returned a non-object JSON response.")
    return payload


def search_products(query: str, max_price: float | None = None) -> dict[str, Any]:
    """Search the UrbanNest catalogue by product requirements and price."""
    params: dict[str, Any] = {"query": query}
    if max_price is not None:
        params["max_price"] = max_price
    response = requests.get(
        f"{BACKEND_URL}/search_products/",
        params=params,
        timeout=REQUEST_TIMEOUT,
    )
    return _json(response)


def get_cart(session_id: str = "default") -> dict[str, Any]:
    """Retrieve all items and totals for the active shopper's cart."""
    response = requests.get(
        f"{BACKEND_URL}/get_cart_items/",
        params={"session_id": _session_id(session_id)},
        timeout=REQUEST_TIMEOUT,
    )
    return _json(response)


def add_to_cart(
    product_name: str,
    quantity: int = 1,
    session_id: str = "default",
) -> dict[str, Any]:
    """Add the requested quantity of a named catalogue product to the cart."""
    response = requests.post(
        f"{BACKEND_URL}/add_product_to_cart/",
        json={
            "product_name": product_name,
            "quantity": quantity,
            "session_id": _session_id(session_id),
        },
        timeout=REQUEST_TIMEOUT,
    )
    return _json(response)


def update_cart(
    product_name: str,
    quantity: int,
    session_id: str = "default",
) -> dict[str, Any]:
    """Set the quantity of a named item already present in the shopper's cart."""
    response = requests.put(
        f"{BACKEND_URL}/update_product_in_cart/",
        json={
            "product_name": product_name,
            "quantity": quantity,
            "session_id": _session_id(session_id),
        },
        timeout=REQUEST_TIMEOUT,
    )
    return _json(response)


def delete_from_cart(
    product_name: str,
    session_id: str = "default",
) -> dict[str, Any]:
    """Remove a named item from the active shopper's cart."""
    response = requests.delete(
        f"{BACKEND_URL}/delete_product_from_cart/",
        json={
            "product_name": product_name,
            "session_id": _session_id(session_id),
        },
        timeout=REQUEST_TIMEOUT,
    )
    return _json(response)


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.getenv(
    "OPENAI_BASE_URL",
    "https://llmgateway-cognizant-assessment.tekstac.com/v1",
).strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

# ``cache_seed=None`` is required by the activity. It disables AutoGen's disk
# cache and prevents the lab's read-only SQLite cache failure.
llm_config: dict[str, Any] = {
    "config_list": [{
        "model": OPENAI_MODEL,
        "api_key": OPENAI_API_KEY or "not-configured",
        "base_url": OPENAI_BASE_URL,
    }],
    "cache_seed": None,
    "temperature": 0.2,
    "timeout": 120,
}


def _is_termination_message(message: dict[str, Any]) -> bool:
    return "TERMINATE" in str(message.get("content") or "").upper()


orchestrator_agent = autogen.AssistantAgent(
    name="orchestrator_agent",
    description="Routes shopping requests to the product-search and cart specialists.",
    system_message=(
        "You are the Shop Buddy orchestration agent. Identify search, cart, or combined intent and coordinate only "
        "the necessary specialist. Never invent catalogue or cart facts. Require specialists to use their registered "
        "backend functions. Once the verified request is complete, give a concise final answer ending in TERMINATE."
    ),
    llm_config=llm_config,
)

search_agent = autogen.AssistantAgent(
    name="product_search_agent",
    description="Finds and recommends real UrbanNest products.",
    system_message=(
        "You are the product-search specialist. For a discovery request, call search_products exactly once with a "
        "concise product phrase and only pass max_price when the shopper gave a numeric budget. Report grounded IDs, "
        "names, prices, and availability to the orchestrator; never invent products."
    ),
    llm_config=llm_config,
)

cart_agent = autogen.AssistantAgent(
    name="cart_management_agent",
    description="Retrieves, adds, updates, and removes items in the shopper's cart.",
    system_message=(
        "You are the cart-management specialist. Call exactly the one registered cart function matching the user's "
        "requested add, update, delete, or retrieve operation. Use the product name from the request and preserve the "
        "provided shopper session. Never claim success until the backend function returns JSON. Report the verified "
        "cart result to the orchestrator and do not repeat a successful mutation."
    ),
    llm_config=llm_config,
)

user_proxy = autogen.UserProxyAgent(
    name="user_proxy",
    description="Executes registered FastAPI backend functions for the specialist agents.",
    human_input_mode="NEVER",
    llm_config=False,
    code_execution_config=False,
    is_termination_msg=_is_termination_message,
    max_consecutive_auto_reply=8,
)


# Search is callable only by the search specialist. The four cart functions
# are callable only by the cart specialist and execute through UserProxyAgent.
autogen.register_function(
    search_products,
    caller=search_agent,
    executor=user_proxy,
    name="search_products",
    description="Search UrbanNest products using requirements and an optional maximum price.",
)
autogen.register_function(
    get_cart,
    caller=cart_agent,
    executor=user_proxy,
    name="get_cart",
    description="Retrieve the active shopper's cart.",
)
autogen.register_function(
    add_to_cart,
    caller=cart_agent,
    executor=user_proxy,
    name="add_to_cart",
    description="Add a named product and requested quantity to the cart.",
)
autogen.register_function(
    update_cart,
    caller=cart_agent,
    executor=user_proxy,
    name="update_cart",
    description="Set the quantity of a named item in the cart.",
)
autogen.register_function(
    delete_from_cart,
    caller=cart_agent,
    executor=user_proxy,
    name="delete_from_cart",
    description="Remove a named item from the cart.",
)


groupchat = autogen.GroupChat(
    agents=[orchestrator_agent, search_agent, cart_agent, user_proxy],
    messages=[],
    max_round=12,
    speaker_selection_method="auto",
    allow_repeat_speaker=False,
)

manager = autogen.GroupChatManager(
    groupchat=groupchat,
    llm_config=llm_config,
    is_termination_msg=_is_termination_message,
)

# Descriptive aliases cover the names used in the written activity while the
# shorter variables match its required reset snippet.
product_search_agent = search_agent
cart_management_agent = cart_agent
group_chat = groupchat
group_chat_manager = manager


def autogen_run(user_query: str = "Show me affordable chairs", session_id: str = "default") -> str:
    """Run one independent autonomous shopping conversation and return its summary."""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY must be configured before running Phase 3.")

    # Required by the activity: AutoGen agents retain history unless both the
    # GroupChat transcript and every individual agent are reset.
    groupchat.messages.clear()
    for agent in [orchestrator_agent, search_agent, cart_agent, user_proxy]:
        agent.reset()

    session_token = _active_session_id.set(session_id)
    try:
        result = user_proxy.initiate_chat(manager, message=user_query, clear_history=True)
    finally:
        _active_session_id.reset(session_token)

    summary = str(getattr(result, "summary", "") or "").replace("TERMINATE", "").strip()
    if summary:
        return summary
    for message in reversed(groupchat.messages):
        content = str(message.get("content") or "").replace("TERMINATE", "").strip()
        if content:
            return content
    raise RuntimeError("AutoGen completed without returning a shopping response.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Shop Buddy Phase 3 AutoGen workflow.")
    parser.add_argument("query", nargs="?", default="Show me affordable chairs")
    parser.add_argument("--session-id", default=f"phase3-cli-{uuid.uuid4()}")
    args = parser.parse_args()
    print(json.dumps({"response": autogen_run(args.query, args.session_id)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "llm_config",
    "search_products",
    "get_cart",
    "add_to_cart",
    "update_cart",
    "delete_from_cart",
    "orchestrator_agent",
    "search_agent",
    "product_search_agent",
    "cart_agent",
    "cart_management_agent",
    "user_proxy",
    "groupchat",
    "group_chat",
    "manager",
    "group_chat_manager",
    "autogen_run",
]
