"""Stateful shopping workflow with orchestrator, search, and cart agent roles."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

from .llm import LLMResponseWriter
from .settings import Settings
from .store import ShopStore


@dataclass
class Intent:
    search: bool = False
    add: bool = False
    update: bool = False
    delete: bool = False
    view: bool = False
    search_query: str = ""
    max_price: float | None = None
    quantity: int = 1
    ordinal: int | None = None

    @property
    def label(self) -> str:
        operations = [name for name in ("search" if self.search else "", "add" if self.add else "", "update" if self.update else "", "delete" if self.delete else "", "view" if self.view else "") if name]
        return "combined" if len(operations) > 1 else (operations[0] if operations else "help")


class ShopWorkflow:
    """Shared shopping engine used by the real LangGraph/CrewAI/AutoGen runtimes.

    Durable state is persisted per shopper, so references such as "the second
    one" continue to work after a browser refresh or backend restart.
    """

    def __init__(self, store: ShopStore, settings: Settings):
        self.store = store
        self.settings = settings
        self.writer = LLMResponseWriter(settings)
        self.graph = None
        self.agent_runtime = None
        if settings.workflow_mode == "langgraph":
            try:
                from .langgraph_runtime import compile_shopping_graph
                self.graph = compile_shopping_graph(self)
            except ImportError:
                # The deterministic engine remains available if an operator opts
                # out of the optional framework package.
                self.graph = None
        elif settings.workflow_mode == "crewai":
            from .crewai_runtime import CrewAIRuntime
            self.agent_runtime = CrewAIRuntime(settings)
        elif settings.workflow_mode == "autogen":
            from .autogen_runtime import AutoGenRuntime
            self.agent_runtime = AutoGenRuntime(settings)

    @staticmethod
    def _quantity(text: str) -> int:
        number = re.search(r"(?:quantity\s*(?:to|of)?|add|buy|need|make it|change (?:it )?to|update (?:it )?to)?\s*(\d{1,2})\b", text, re.I)
        if number:
            return max(1, min(99, int(number.group(1))))
        words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
        return next((value for word, value in words.items() if re.search(rf"\b{word}\b", text, re.I)), 1)

    @staticmethod
    def _ordinal(text: str) -> int | None:
        match = re.search(r"\b(?:the\s+)?(first|second|third|fourth|fifth)(?:\s+one|\s+item)?\b|\b(\d+)(?:st|nd|rd|th)\s+(?:one|item)\b", text, re.I)
        if not match:
            return None
        word = match.group(1)
        if word:
            return {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}[word.lower()]
        return int(match.group(2))

    def classify(self, text: str) -> Intent:
        lowered = text.lower()
        add = bool(re.search(r"\b(add|put|buy|purchase)\b", lowered))
        update = bool(re.search(r"\b(update|change|increase|decrease|set)\b.*\b(quantity|qty|to|it)\b|\bquantity\b", lowered))
        delete = bool(re.search(r"\b(remove|delete|drop|take .* out)\b", lowered))
        view = bool(re.search(r"\b(show|view|see|what(?:'s| is))\b.*\bcart\b|\bcart\b.*\b(show|view|see)\b", lowered))
        explicit_search = bool(re.search(r"\b(show|find|search|recommend|browse|looking for|need)\b", lowered))
        product_words = r"chair|desk|sofa|table|lamp|pad|accessor|furniture|seating"
        search = explicit_search and (bool(re.search(product_words, lowered)) or "under" in lowered or "below" in lowered)
        # An add with a named product must discover it before adding unless it uses memory.
        if add and re.search(product_words, lowered) and not re.search(r"\b(the |it|one|first|second|third)\b", lowered):
            search = True
        price_match = re.search(r"\b(?:under|below|less than|budget of)\s*\$?\s*([\d,]+(?:\.\d{1,2})?)", lowered)
        max_price = float(price_match.group(1).replace(",", "")) if price_match else None
        cleanup = re.sub(r"\b(show|find|search|recommend|browse|looking|for|i|need|want|please|can|you|me|an?|the|and|add|put|buy|purchase|to|my|cart|update|change|quantity|qty|remove|delete|from|under|below|less|than|budget|of|it|one|first|second|third|fourth|fifth|make|set)\b", " ", lowered)
        cleanup = re.sub(r"\$?\d+(?:,\d{3})*(?:\.\d+)?", " ", cleanup)
        cleanup = re.sub(r"[^a-z0-9\s-]", " ", cleanup)
        search_query = re.sub(r"\s+", " ", cleanup).strip()
        return Intent(search, add, update, delete, view, search_query, max_price, self._quantity(text), self._ordinal(text))

    @staticmethod
    def _product_summary(product: dict[str, Any]) -> dict[str, Any]:
        return {key: product[key] for key in ("id", "sku", "title", "category", "price", "description", "stock", "rating", "material", "color")}

    def _resolve_product(self, intent: Intent, memory: dict[str, Any], found: list[dict[str, Any]]) -> dict[str, Any] | None:
        candidates = found or memory["last_results"]
        if intent.ordinal and len(candidates) >= intent.ordinal:
            return candidates[intent.ordinal - 1]
        if memory.get("selected_product_id") and not intent.search_query:
            selected = self.store.get_product(memory["selected_product_id"])
            if selected:
                return selected
        if candidates:
            if intent.quantity > 1:
                single_item = next((item for item in candidates if "set of" not in item["title"].lower()), None)
                if single_item:
                    return single_item
            return candidates[0]
        if intent.search_query:
            return self.store.find_product(intent.search_query)
        return None

    @staticmethod
    def _local_message(intent: Intent, results: list[dict[str, Any]], events: list[str], cart: dict[str, Any]) -> str:
        parts: list[str] = []
        if results:
            preview = ", ".join(f"{p['title']} (${p['price']:,.0f})" for p in results[:3])
            parts.append(f"I found {len(results)} match{'es' if len(results) != 1 else ''}: {preview}.")
        elif intent.search:
            parts.append("I could not find a matching in-stock piece. Try a broader style, category, or budget.")
        parts.extend(events)
        if intent.view and not cart["items"]:
            parts.append("Your cart is currently empty.")
        if cart["items"] and (intent.add or intent.update or intent.delete or intent.view):
            parts.append(f"Your cart has {cart['item_count']} item{'s' if cart['item_count'] != 1 else ''}, totaling ${cart['total']:,.2f}.")
        if not parts:
            parts.append("I can help you find furniture, add items, adjust quantities, or show your cart. Try “show office chairs under $500”.")
        return " ".join(parts)

    def run(self, message: str, session_id: str) -> dict[str, Any]:
        if self.graph is not None:
            graph_state = self.graph.invoke(
                {"message": message, "session_id": session_id},
                config={"configurable": {"thread_id": session_id}},
            )
            return graph_state["result"]
        if self.agent_runtime is not None and self.agent_runtime.configured:
            try:
                if self.settings.workflow_mode == "crewai":
                    response = self.agent_runtime.kickoff(message, session_id)
                else:
                    response = self.agent_runtime.initiate(message, session_id)
                return self._framework_result(message, session_id, response)
            except Exception:
                # Keep the storefront operational when a gateway is unavailable.
                # LLMResponseWriter will independently attempt the next provider.
                result = self._run_local(message, session_id)
                result["workflow"] = self.settings.workflow_mode
                result["trace"].insert(0, {
                    "agent": f"{self.settings.workflow_mode.title()} Runtime",
                    "status": "fallback",
                    "detail": "The agent provider was unavailable; the deterministic tool workflow completed the request.",
                })
                return result
        return self._run_local(message, session_id)

    def _framework_result(self, message: str, session_id: str, response: str) -> dict[str, Any]:
        """Normalize a successful CrewAI/AutoGen result for the React client."""
        memory = self.store.load_memory(session_id)
        intent = self.classify(message)
        products = self.store.search_products(intent.search_query, intent.max_price) if intent.search else []
        cart = self.store.get_cart(session_id)
        clean_response = response.replace("TERMINATE", "").strip() or self._local_message(intent, products, [], cart)
        selected_id = memory.get("selected_product_id")
        self.store.save_memory(
            session_id,
            [*memory["messages"], {"role": "user", "content": message}, {"role": "assistant", "content": clean_response}],
            products or memory["last_results"],
            selected_id,
        )
        framework = "CrewAI" if self.settings.workflow_mode == "crewai" else "AutoGen"
        return {
            "message": clean_response,
            "intent": intent.label,
            "products": [self._product_summary(product) for product in products],
            "cart": cart,
            "workflow": self.settings.workflow_mode,
            "provider": self.settings.configured_provider,
            "trace": [{
                "agent": f"{framework} Multi-Agent Runtime",
                "status": "completed",
                "detail": "Specialized agents collaborated and executed registered FastAPI tools.",
            }],
            "tool_results": [],
        }

    @staticmethod
    def intent_to_dict(intent: Intent) -> dict[str, Any]:
        """Return a checkpointer-safe representation of a classified request."""
        return asdict(intent)

    @staticmethod
    def intent_from_dict(payload: dict[str, Any]) -> Intent:
        return Intent(**payload)

    def execute_search_stage(self, intent: Intent) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Execute the product-search tool and return its structured tool result."""
        products = self.store.search_products(intent.search_query, intent.max_price)
        return products, {
            "tool": "Search Products",
            "status": "completed",
            "count": len(products),
            "query": intent.search_query,
            "max_price": intent.max_price,
        }

    def execute_cart_stage(
        self,
        intent: Intent,
        session_id: str,
        memory: dict[str, Any],
        results: list[dict[str, Any]],
        selected_id: int | None,
    ) -> tuple[list[str], int | None, list[dict[str, Any]], dict[str, Any]]:
        """Execute only the requested cart tools and expose every tool outcome."""
        events: list[str] = []
        tool_results: list[dict[str, Any]] = []
        operation: dict[str, Any] = {"requested": intent.label, "completed": []}

        if intent.add:
            product = self._resolve_product(intent, memory, results)
            if product:
                try:
                    outcome = self.store.add_to_cart(session_id, product["id"], intent.quantity)
                    selected_id = product["id"]
                    events.append(f"Added {intent.quantity} x {product['title']} to your cart.")
                    tool_results.append({"tool": "AddProductToCart", "status": "completed", "result": outcome})
                    operation["completed"].append("add")
                except (LookupError, ValueError) as exc:
                    events.append(str(exc))
                    tool_results.append({"tool": "AddProductToCart", "status": "failed", "error": str(exc)})
            else:
                message = "Tell me which product you would like to add, or search for it first."
                events.append(message)
                tool_results.append({"tool": "AddProductToCart", "status": "failed", "error": message})

        if intent.update:
            product = self._resolve_product(intent, memory, results)
            try:
                outcome = self.store.update_cart(
                    session_id,
                    intent.quantity,
                    product_id=product["id"] if product and not intent.search_query else None,
                    product_name=intent.search_query or None,
                )
                selected_id = product["id"] if product else selected_id
                events.append(f"Updated {outcome['title']} to quantity {intent.quantity}.")
                tool_results.append({"tool": "UpdateCartItem", "status": "completed", "result": outcome})
                operation["completed"].append("update")
            except (LookupError, ValueError) as exc:
                events.append(str(exc))
                tool_results.append({"tool": "UpdateCartItem", "status": "failed", "error": str(exc)})

        if intent.delete:
            product = self._resolve_product(intent, memory, results)
            try:
                outcome = self.store.delete_from_cart(
                    session_id,
                    product_id=product["id"] if product and not intent.search_query else None,
                    product_name=intent.search_query or None,
                )
                events.append(f"Removed {outcome['title']} from your cart.")
                tool_results.append({"tool": "DeleteCartItem", "status": "completed", "result": outcome})
                operation["completed"].append("delete")
            except LookupError as exc:
                events.append(str(exc))
                tool_results.append({"tool": "DeleteCartItem", "status": "failed", "error": str(exc)})

        if intent.view:
            cart = self.store.get_cart(session_id)
            tool_results.append({"tool": "GetCartItems", "status": "completed", "result": cart})
            operation["completed"].append("view")

        return events, selected_id, tool_results, operation

    def finalize_response(
        self,
        message: str,
        session_id: str,
        intent: Intent,
        memory: dict[str, Any],
        results: list[dict[str, Any]],
        events: list[str],
        selected_id: int | None,
        trace: list[dict[str, str]],
        tool_results: list[dict[str, Any]] | None = None,
        workflow_name: str | None = None,
    ) -> dict[str, Any]:
        """Create the grounded response and commit the conversation checkpoint."""
        cart = self.store.get_cart(session_id)
        facts = {
            "intent": intent.label,
            "results": [self._product_summary(product) for product in results[:5]],
            "events": events,
            "cart": cart,
        }
        generated, provider = self.writer.write(message, facts)
        response_message = generated or self._local_message(intent, results, events, cart)
        completed_trace = [*trace, {
            "agent": "Response Agent",
            "status": "completed",
            "detail": f"Response prepared with {provider} provider.",
        }]
        messages = memory["messages"] + [
            {"role": "user", "content": message},
            {"role": "assistant", "content": response_message},
        ]
        self.store.save_memory(session_id, messages, results or memory["last_results"], selected_id)
        return {
            "message": response_message,
            "intent": intent.label,
            "products": [self._product_summary(product) for product in results],
            "cart": cart,
            "workflow": workflow_name or self.settings.workflow_mode,
            "provider": provider,
            "trace": completed_trace,
            "tool_results": tool_results or [],
        }

    def _run_local(self, message: str, session_id: str) -> dict[str, Any]:
        memory = self.store.load_memory(session_id)
        intent = self.classify(message)
        trace = [{"agent": "Orchestrator Agent", "status": "completed", "detail": f"Intent classified as {intent.label}."}]
        results: list[dict[str, Any]] = []
        selected_id = memory.get("selected_product_id")
        tool_results: list[dict[str, Any]] = []

        if intent.search:
            results, search_result = self.execute_search_stage(intent)
            tool_results.append(search_result)
            trace.append({"agent": "Product Search Agent", "status": "completed", "detail": f"Search Products tool returned {len(results)} products."})
        events, selected_id, cart_results, operation = self.execute_cart_stage(
            intent, session_id, memory, results, selected_id
        )
        tool_results.extend(cart_results)
        if cart_results:
            completed = ", ".join(operation["completed"]) or "requested operation"
            trace.append({"agent": "Cart Management Agent", "status": "completed", "detail": f"Cart tools processed: {completed}."})
        return self.finalize_response(
            message,
            session_id,
            intent,
            memory,
            results,
            events,
            selected_id,
            trace,
            tool_results,
        )
