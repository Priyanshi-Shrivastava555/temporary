"""CrewAI collaborative phase with real agents, tasks, and HTTP tools."""
from __future__ import annotations

import os
from contextvars import ContextVar
from pathlib import Path
from typing import Any

# CrewAI resolves and creates its task/RAG storage directory while the package
# is imported. Keep that state inside the project so restricted Windows VDIs
# and Linux evaluators do not depend on a writable user-profile directory.
_storage_setting = Path(os.getenv("CREWAI_STORAGE_DIR", "crewai"))
if not _storage_setting.is_absolute():
    _storage_setting = Path(__file__).resolve().parents[1] / ".runtime-data" / _storage_setting
_storage_setting.mkdir(parents=True, exist_ok=True)
os.environ["CREWAI_STORAGE_DIR"] = str(_storage_setting)
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
# CrewAI uses this flag only to suppress its interactive first-run tracing
# prompt. Assessment runs are non-interactive and tracing is already disabled.
os.environ.setdefault("CREWAI_TESTING", "true")

from crewai import Agent, Crew, LLM, Process, Task
from crewai.tools import tool

from .langflow_components import (
    add_product_to_cart,
    delete_cart_item,
    get_cart_items,
    search_products,
    update_cart_item,
)
from .settings import Settings


_active_session_id: ContextVar[str | None] = ContextVar("shop_buddy_crewai_session", default=None)


def _request_session_id(supplied_session_id: str) -> str:
    """Keep tool calls scoped to the /chat request even if the LLM omits the ID."""
    return _active_session_id.get() or supplied_session_id


@tool("Search Products")
def search_tool(query: str, max_price: float | None = None) -> dict[str, Any]:
    """Search the FastAPI product catalogue using requirements and an optional maximum price."""
    return search_products(query, max_price)


@tool("Retrieve Cart")
def retrieve_tool(session_id: str = "default") -> dict[str, Any]:
    """Retrieve every item and total from the shopper's FastAPI cart."""
    return get_cart_items(_request_session_id(session_id))


@tool("Create Cart Item")
def create_tool(product_id: int, quantity: int = 1, session_id: str = "default") -> dict[str, Any]:
    """Add a catalogue product and quantity to the shopper's FastAPI cart."""
    return add_product_to_cart(product_id, quantity, _request_session_id(session_id))


@tool("Update Cart Item")
def update_tool(product_id: int, quantity: int, session_id: str = "default") -> dict[str, Any]:
    """Set the quantity of a product already in the shopper's FastAPI cart."""
    return update_cart_item(product_id, quantity, _request_session_id(session_id))


@tool("Delete Cart Item")
def delete_tool(product_id: int, session_id: str = "default") -> dict[str, Any]:
    """Remove a product from the shopper's FastAPI cart."""
    return delete_cart_item(product_id, _request_session_id(session_id))


def _crew_llm(settings: Settings) -> LLM | None:
    if settings.openai_api_key:
        return LLM(
            model=f"openai/{settings.openai_model}",
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            temperature=0.2,
        )
    if settings.gemini_api_key:
        return LLM(
            model=f"gemini/{settings.gemini_model}",
            api_key=settings.gemini_api_key,
            temperature=0.2,
        )
    return None


class CrewAIRuntime:
    """Construct the three requested CrewAI agents and sequential tasks."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm = _crew_llm(settings)
        self.crew: Crew | None = None
        self.agents: dict[str, Agent] = {}
        self.tasks: list[Task] = []
        if self.llm is not None:
            self._build()

    @property
    def configured(self) -> bool:
        return self.crew is not None

    def _build(self) -> None:
        orchestrator = Agent(
            role="Shop Buddy Orchestrator Agent",
            goal="Classify the customer's intent and coordinate only the shopping specialists that are needed.",
            backstory="You manage UrbanNest shopping requests accurately and never invent product or cart data.",
            llm=self.llm,
            allow_delegation=True,
            max_iter=8,
            verbose=False,
        )
        search_agent = Agent(
            role="Product Search Agent",
            goal="Discover and recommend catalogue products that satisfy the customer's requirements.",
            backstory="You are an UrbanNest catalogue specialist focused on fit, budget, and accurate product details.",
            tools=[search_tool],
            llm=self.llm,
            allow_delegation=False,
            max_iter=8,
            verbose=False,
        )
        cart_agent = Agent(
            role="Cart Management Agent",
            goal="Carry out requested cart operations safely and summarize the resulting cart.",
            backstory="You are a precise shopping-cart specialist who confirms every completed operation.",
            tools=[retrieve_tool, create_tool, update_tool, delete_tool],
            llm=self.llm,
            allow_delegation=False,
            max_iter=8,
            verbose=False,
        )
        orchestration_task = Task(
            description=(
                "Analyze this request: {user_query}. Identify search, add, update, delete, or view intent. "
                "The shopper session is {session_id}. Produce a compact routing brief for the specialists."
            ),
            expected_output="A routing brief naming only the required search and/or cart work.",
            agent=orchestrator,
        )
        search_task = Task(
            description=(
                "Use the routing brief and customer request {user_query}. If product discovery is required, "
                "call Search Products exactly once with the concise product phrase and requested maximum price, then "
                "return grounded candidates including their numeric product IDs. Do not repeatedly broaden the query. "
                "Never invent a maximum price: pass null unless the customer supplied an explicit numeric budget. "
                "If discovery is not required, do not call a tool and explicitly report that search was skipped."
            ),
            expected_output="Grounded product candidates or a concise skipped-search result.",
            agent=search_agent,
            context=[orchestration_task],
        )
        cart_task = Task(
            description=(
                "Use the prior work to address {user_query} for session {session_id}. For an add, update, delete, or "
                "view request you MUST call exactly the matching cart tool once, using session_id={session_id} and a "
                "numeric product ID grounded in search results or the retrieved cart. Never claim an operation succeeded "
                "without a successful tool response. For search-only requests, do not call a cart tool or mutate the "
                "cart. End with a concise factual result."
            ),
            expected_output="A factual user-facing shopping result based only on tool responses.",
            agent=cart_agent,
            context=[orchestration_task, search_task],
        )
        self.agents = {"orchestrator": orchestrator, "search": search_agent, "cart": cart_agent}
        self.tasks = [orchestration_task, search_task, cart_task]
        self.crew = Crew(
            agents=list(self.agents.values()),
            tasks=self.tasks,
            process=Process.sequential,
            verbose=False,
            memory=False,
        )

    def kickoff(self, user_query: str, session_id: str) -> str:
        if self.crew is None:
            raise RuntimeError("CrewAI requires OPENAI_API_KEY or GEMINI_API_KEY.")
        token = _active_session_id.set(session_id)
        try:
            return str(self.crew.kickoff(inputs={"user_query": user_query, "session_id": session_id}))
        finally:
            _active_session_id.reset(token)
