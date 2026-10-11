"""Native LangGraph workflow with typed shared state and durable memory."""
from __future__ import annotations

from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph


class ShopState(TypedDict, total=False):
    """Shared state required by the Shop Buddy LangGraph phase."""

    message: str
    session_id: str
    messages: list[dict[str, str]]
    current_user_intent: dict[str, Any]
    product_search_results: list[dict[str, Any]]
    cart_operation_details: dict[str, Any]
    tool_execution_results: list[dict[str, Any]]
    workflow_progress: list[dict[str, str]]
    memory: dict[str, Any]
    selected_product_id: int | None
    events: list[str]
    route: str
    result: dict[str, Any]


def compile_shopping_graph(workflow: Any):
    """Compile Orchestrator -> Search/Cart -> Response with a checkpointer.

    LangGraph's MemorySaver preserves live thread state. SQLite remains the
    durable checkpoint across API restarts and is loaded by the orchestrator.
    """

    graph = StateGraph(ShopState)

    def orchestrator(state: ShopState) -> dict[str, Any]:
        memory = workflow.store.load_memory(state["session_id"])
        intent = workflow.classify(state["message"])
        if intent.search:
            route = "search"
        elif intent.add or intent.update or intent.delete or intent.view:
            route = "cart"
        else:
            route = "response"
        return {
            "messages": [*memory["messages"], {"role": "user", "content": state["message"]}],
            "current_user_intent": workflow.intent_to_dict(intent),
            "product_search_results": [],
            "cart_operation_details": {},
            "tool_execution_results": [],
            "workflow_progress": [{
                "agent": "Orchestrator Agent",
                "status": "completed",
                "detail": f"Intent classified as {intent.label}; routed to {route}.",
            }],
            "memory": memory,
            "selected_product_id": memory.get("selected_product_id"),
            "events": [],
            "route": route,
        }

    def product_search(state: ShopState) -> dict[str, Any]:
        intent = workflow.intent_from_dict(state["current_user_intent"])
        products, tool_result = workflow.execute_search_stage(intent)
        has_cart_work = intent.add or intent.update or intent.delete or intent.view
        return {
            "product_search_results": products,
            "tool_execution_results": [*state["tool_execution_results"], tool_result],
            "workflow_progress": [*state["workflow_progress"], {
                "agent": "Product Search Agent",
                "status": "completed",
                "detail": f"Search Products tool returned {len(products)} products.",
            }],
            "route": "cart" if has_cart_work else "response",
        }

    def cart_management(state: ShopState) -> dict[str, Any]:
        intent = workflow.intent_from_dict(state["current_user_intent"])
        events, selected_id, tool_results, operation = workflow.execute_cart_stage(
            intent,
            state["session_id"],
            state["memory"],
            state.get("product_search_results", []),
            state.get("selected_product_id"),
        )
        completed = ", ".join(operation["completed"]) or "requested operation"
        return {
            "events": events,
            "selected_product_id": selected_id,
            "cart_operation_details": operation,
            "tool_execution_results": [*state["tool_execution_results"], *tool_results],
            "workflow_progress": [*state["workflow_progress"], {
                "agent": "Cart Management Agent",
                "status": "completed",
                "detail": f"Cart tools processed: {completed}.",
            }],
            "route": "response",
        }

    def response(state: ShopState) -> dict[str, Any]:
        intent = workflow.intent_from_dict(state["current_user_intent"])
        result = workflow.finalize_response(
            state["message"], state["session_id"], intent, state["memory"],
            state.get("product_search_results", []), state.get("events", []),
            state.get("selected_product_id"), state["workflow_progress"],
            state["tool_execution_results"], workflow_name="langgraph",
        )
        return {
            "messages": [*state["messages"], {"role": "assistant", "content": result["message"]}],
            "result": result,
        }

    graph.add_node("orchestrator", orchestrator)
    graph.add_node("product_search", product_search)
    graph.add_node("cart_management", cart_management)
    graph.add_node("response", response)
    graph.add_edge(START, "orchestrator")
    graph.add_conditional_edges(
        "orchestrator", lambda state: state["route"],
        {"search": "product_search", "cart": "cart_management", "response": "response"},
    )
    graph.add_conditional_edges(
        "product_search", lambda state: state["route"],
        {"cart": "cart_management", "response": "response"},
    )
    graph.add_edge("cart_management", "response")
    graph.add_edge("response", END)
    return graph.compile(checkpointer=MemorySaver())
