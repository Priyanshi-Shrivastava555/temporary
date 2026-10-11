"""AutoGen 0.2 autonomous phase with registered FastAPI tools."""
from __future__ import annotations

from typing import Any

import autogen

from .langflow_components import (
    add_product_to_cart,
    delete_cart_item,
    get_cart_items,
    search_products as api_search_products,
    update_cart_item,
)
from .settings import Settings


def search_products(query: str, max_price: float | None = None) -> dict[str, Any]:
    """Search products through the FastAPI Search Products endpoint."""
    return api_search_products(query, max_price)


def get_cart(session_id: str = "default") -> dict[str, Any]:
    """Retrieve a shopper's cart through FastAPI."""
    return get_cart_items(session_id)


def add_to_cart(product_id: int, quantity: int = 1, session_id: str = "default") -> dict[str, Any]:
    """Add a product to a shopper's cart through FastAPI."""
    return add_product_to_cart(product_id, quantity, session_id)


def update_cart(product_id: int, quantity: int, session_id: str = "default") -> dict[str, Any]:
    """Update a cart product quantity through FastAPI."""
    return update_cart_item(product_id, quantity, session_id)


def delete_from_cart(product_id: int, session_id: str = "default") -> dict[str, Any]:
    """Delete a product from a shopper's cart through FastAPI."""
    return delete_cart_item(product_id, session_id)


def _llm_config(settings: Settings) -> dict[str, Any] | None:
    if settings.openai_api_key:
        provider = {
            "model": settings.openai_model,
            "api_key": settings.openai_api_key,
        }
        if settings.openai_base_url:
            provider["base_url"] = settings.openai_base_url
        return {"config_list": [provider], "cache_seed": None, "temperature": 0.2}
    if settings.gemini_api_key:
        return {
            "config_list": [{
                "model": settings.gemini_model,
                "api_key": settings.gemini_api_key,
                "api_type": "google",
            }],
            "cache_seed": None,
            "temperature": 0.2,
        }
    return None


class AutoGenRuntime:
    """Create the four requested agents and their managed GroupChat."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm_config = _llm_config(settings)
        self.orchestrator_agent = None
        self.search_agent = None
        self.cart_agent = None
        self.user_proxy = None
        self.groupchat = None
        self.manager = None
        if self.llm_config is not None:
            self._build()

    @property
    def configured(self) -> bool:
        return self.manager is not None

    def _build(self) -> None:
        termination = lambda message: "TERMINATE" in str(message.get("content") or "")
        self.orchestrator_agent = autogen.AssistantAgent(
            name="orchestrator_agent",
            description="Routes product-search and shopping-cart work to the correct specialist.",
            system_message=(
                "Classify the user's shopping intent, coordinate only required specialists, and ensure the final "
                "answer is grounded in tool results. End completed work with TERMINATE."
            ),
            llm_config=self.llm_config,
        )
        self.search_agent = autogen.AssistantAgent(
            name="product_search_agent",
            description="Searches the UrbanNest catalogue and recommends products.",
            system_message="Use search_products for discovery. Never invent products, prices, or stock.",
            llm_config=self.llm_config,
        )
        self.cart_agent = autogen.AssistantAgent(
            name="cart_management_agent",
            description="Adds, retrieves, updates, and deletes UrbanNest cart items.",
            system_message="Use the registered cart tools and report only confirmed cart operations.",
            llm_config=self.llm_config,
        )
        self.user_proxy = autogen.UserProxyAgent(
            name="user_proxy",
            description="Executes registered backend tools for the assistant agents.",
            human_input_mode="NEVER",
            llm_config=False,
            code_execution_config=False,
            is_termination_msg=termination,
            max_consecutive_auto_reply=8,
        )
        autogen.register_function(
            search_products,
            caller=self.search_agent,
            executor=self.user_proxy,
            name="search_products",
            description="Search UrbanNest products by requirements and optional maximum price.",
        )
        for function, name, description in (
            (get_cart, "get_cart", "Retrieve the current shopping cart."),
            (add_to_cart, "add_to_cart", "Add a product and quantity to the cart."),
            (update_cart, "update_cart", "Set an existing cart product quantity."),
            (delete_from_cart, "delete_from_cart", "Remove a product from the cart."),
        ):
            autogen.register_function(
                function,
                caller=self.cart_agent,
                executor=self.user_proxy,
                name=name,
                description=description,
            )
        self.groupchat = autogen.GroupChat(
            agents=[self.orchestrator_agent, self.search_agent, self.cart_agent, self.user_proxy],
            messages=[],
            max_round=10,
            speaker_selection_method="auto",
            allow_repeat_speaker=False,
        )
        self.manager = autogen.GroupChatManager(
            groupchat=self.groupchat,
            llm_config=self.llm_config,
            is_termination_msg=termination,
        )

    def reset(self) -> None:
        if not self.configured:
            return
        self.groupchat.messages.clear()
        for agent in (self.orchestrator_agent, self.search_agent, self.cart_agent, self.user_proxy):
            agent.reset()

    def initiate(self, user_query: str, session_id: str) -> str:
        if not self.configured:
            raise RuntimeError("AutoGen requires OPENAI_API_KEY or GEMINI_API_KEY.")
        self.reset()
        result = self.user_proxy.initiate_chat(
            self.manager,
            message=f"Shopper session: {session_id}\nRequest: {user_query}",
            clear_history=True,
        )
        return str(result.summary or "")
