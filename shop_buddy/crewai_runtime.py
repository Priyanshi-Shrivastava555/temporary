"""CrewAI collaborative phase with real agents, tasks, and HTTP tools."""
from __future__ import annotations

from typing import Any

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


@tool("Search Products")
def search_tool(query: str, max_price: float | None = None) -> dict[str, Any]:
    """Search the FastAPI product catalogue using requirements and an optional maximum price."""
    return search_products(query, max_price)


@tool("Retrieve Cart")
def retrieve_tool(session_id: str = "default") -> dict[str, Any]:
    """Retrieve every item and total from the shopper's FastAPI cart."""
    return get_cart_items(session_id)


@tool("Create Cart Item")
def create_tool(product_id: int, quantity: int = 1, session_id: str = "default") -> dict[str, Any]:
    """Add a catalogue product and quantity to the shopper's FastAPI cart."""
    return add_product_to_cart(product_id, quantity, session_id)


@tool("Update Cart Item")
def update_tool(product_id: int, quantity: int, session_id: str = "default") -> dict[str, Any]:
    """Set the quantity of a product already in the shopper's FastAPI cart."""
    return update_cart_item(product_id, quantity, session_id)


@tool("Delete Cart Item")
def delete_tool(product_id: int, session_id: str = "default") -> dict[str, Any]:
    """Remove a product from the shopper's FastAPI cart."""
    return delete_cart_item(product_id, session_id)


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
            verbose=False,
        )
        search_agent = Agent(
            role="Product Search Agent",
            goal="Discover and recommend catalogue products that satisfy the customer's requirements.",
            backstory="You are an UrbanNest catalogue specialist focused on fit, budget, and accurate product details.",
            tools=[search_tool],
            llm=self.llm,
            allow_delegation=False,
            verbose=False,
        )
        cart_agent = Agent(
            role="Cart Management Agent",
            goal="Carry out requested cart operations safely and summarize the resulting cart.",
            backstory="You are a precise shopping-cart specialist who confirms every completed operation.",
            tools=[retrieve_tool, create_tool, update_tool, delete_tool],
            llm=self.llm,
            allow_delegation=False,
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
                "use Search Products and return grounded candidates. Otherwise explicitly report that search was skipped."
            ),
            expected_output="Grounded product candidates or a concise skipped-search result.",
            agent=search_agent,
            context=[orchestration_task],
        )
        cart_task = Task(
            description=(
                "Use the prior work to address {user_query} for session {session_id}. Perform only requested cart "
                "operations with your tools; for search-only requests do not mutate the cart. End with a concise result."
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
        return str(self.crew.kickoff(inputs={"user_query": user_query, "session_id": session_id}))
