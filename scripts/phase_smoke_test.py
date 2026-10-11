"""Evaluation-oriented smoke tests for the five Shop Buddy phase profiles."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import uuid
from typing import Any

import requests


WORKFLOW_BY_PHASE = {
    "phase1": "langgraph",
    "phase2": "crewai",
    "phase3": "autogen",
    "phase4": "langgraph",
    "phase5": "langgraph",
}


class PhaseSmokeTest:
    def __init__(self, phase: str, api_url: str, langflow_url: str):
        self.phase = phase
        self.api_url = api_url.rstrip("/")
        self.langflow_url = langflow_url.rstrip("/")
        self.session_id = f"{phase}-smoke-{uuid.uuid4()}"
        self.sessions_to_clean = {self.session_id}
        self.has_ai_key = bool(os.getenv("OPENAI_API_KEY") or os.getenv("GEMINI_API_KEY"))

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = requests.request(method, f"{self.api_url}{path}", timeout=kwargs.pop("timeout", 120), **kwargs)
        response.raise_for_status()
        return response.json()

    def chat(self, message: str, session_id: str | None = None) -> dict[str, Any]:
        active_session = session_id or self.session_id
        self.sessions_to_clean.add(active_session)
        payload = self.request("POST", "/chat", json={"message": message, "session_id": active_session}, timeout=300)
        assert payload["workflow"] == WORKFLOW_BY_PHASE[self.phase], payload
        print(f"PASS [{self.phase}]: {message} -> {payload['intent']}")
        return payload

    def cart(self, session_id: str | None = None) -> dict[str, Any]:
        return self.request("GET", "/get_cart_items/", params={"session_id": session_id or self.session_id})

    @staticmethod
    def item(cart: dict[str, Any], text: str) -> dict[str, Any] | None:
        return next((item for item in cart["items"] if text.lower() in item["title"].lower()), None)

    def seed_desk_pad(self) -> None:
        result = self.request("GET", "/search_products/", params={"query": "desk pad"})
        assert result["products"], "Desk pad was not found for delete-tool setup."
        self.request("POST", "/add_product_to_cart/", json={
            "product_id": result["products"][0]["id"], "quantity": 1, "session_id": self.session_id,
        })

    def require_live_agent(self, responses: list[dict[str, Any]]) -> None:
        if not self.has_ai_key or self.phase not in {"phase2", "phase3"}:
            return
        expected = "CrewAI Multi-Agent Runtime" if self.phase == "phase2" else "AutoGen Multi-Agent Runtime"
        for payload in responses:
            assert any(
                entry.get("agent") == expected and entry.get("status") == "completed"
                for entry in payload.get("trace", [])
            ), f"{expected} fell back instead of completing with the configured AI provider: {payload.get('trace')}"

    def verify_framework_structure(self) -> None:
        """Build phase runtimes without a network call and verify evaluator-visible structure."""
        from shop_buddy.settings import Settings

        runtime_data = Path.cwd() / ".runtime-data"
        runtime_data.mkdir(parents=True, exist_ok=True)
        os.environ["XDG_DATA_HOME"] = str(runtime_data)
        os.environ["LOCALAPPDATA"] = str(runtime_data)
        os.environ["CREWAI_STORAGE_DIR"] = "shop_buddy"
        if os.name == "nt":
            # appdirs resolves Windows known folders through the shell rather
            # than LOCALAPPDATA. Keep this smoke-only CrewAI database inside
            # the repository sandbox; Linux uses XDG_DATA_HOME above.
            import appdirs

            appdirs.user_data_dir = lambda *_args, **_kwargs: str(runtime_data)
        settings = Settings(
            database_path=Path(":memory:"),
            openai_api_key="structure-check-only",
            openai_base_url="https://example.invalid/v1",
            openai_model="gpt-4o-mini",
            gemini_api_key=None,
            gemini_model="gemini-3.5-flash",
            workflow_mode=WORKFLOW_BY_PHASE[self.phase],
        )
        if self.phase == "phase2":
            from shop_buddy.crewai_runtime import CrewAIRuntime

            runtime = CrewAIRuntime(settings)
            assert set(runtime.agents) == {"orchestrator", "search", "cart"}
            assert len(runtime.tasks) == 3 and runtime.crew is not None
            assert len(runtime.agents["search"].tools) == 1
            assert len(runtime.agents["cart"].tools) == 4
            print("PASS [phase2]: three CrewAI agents, three tasks, and five assigned tools")
        elif self.phase == "phase3":
            from shop_buddy.autogen_runtime import AutoGenRuntime

            runtime = AutoGenRuntime(settings)
            assert runtime.llm_config["cache_seed"] is None
            assert runtime.groupchat is not None and len(runtime.groupchat.agents) == 4
            runtime.groupchat.messages.append({"role": "user", "content": "reset check"})
            runtime.reset()
            assert runtime.groupchat.messages == []
            print("PASS [phase3]: four AutoGen agents, GroupChat, registered execution runtime, and reset behavior")

    def run_phase1_or_5(self) -> None:
        queries = [
            "Show me office chairs.",
            "Find an office chair under $500 and add it to my cart.",
            "Add 2 conference chairs to my cart.",
            "Change quantity to 3.",
            "Show my cart.",
            "Remove the conference chairs from my cart.",
        ]
        responses = [self.chat(query) for query in queries]
        assert responses[0]["products"], "Office-chair search returned no products."
        assert responses[1]["intent"] == "combined", "Combined search/add routing failed."
        conference = self.item(responses[2]["cart"], "conference")
        assert conference and conference["quantity"] == 2
        conference = self.item(responses[3]["cart"], "conference")
        assert conference and conference["quantity"] == 3
        assert any(result["tool"] == "GetCartItems" for result in responses[4]["tool_results"])
        assert self.item(responses[5]["cart"], "conference") is None
        if self.phase == "phase1":
            self.verify_langflow()

    def run_agent_phase(self, product: str) -> None:
        self.seed_desk_pad()
        queries = [
            "Show me affordable chairs.",
            "Find a desk under 5000.",
            f"Add 2 {product} to my cart.",
            f"Update {product} quantity to 3.",
            "Delete desk pad from my cart.",
        ]
        responses = [self.chat(query) for query in queries]
        assert responses[0]["products"], "Affordable-chair search returned no products."
        assert responses[1]["products"] and all(item["price"] <= 5000 for item in responses[1]["products"])
        selected = self.item(self.cart(), product.split()[0])
        assert selected and selected["quantity"] == 3
        assert self.item(self.cart(), "desk pad") is None
        self.require_live_agent(responses)

    def run_phase4(self) -> None:
        self.run_agent_phase("conference chairs")
        memory_session = f"phase4-memory-{uuid.uuid4()}"
        self.sessions_to_clean.add(memory_session)
        first = self.chat("Show me office chairs under $500.", memory_session)
        assert len(first["products"]) >= 2
        self.chat("Add the second one to my cart.", memory_session)
        self.chat("Increase its quantity to 3.", memory_session)
        selected = self.item(self.cart(memory_session), "Cedar Executive Chair")
        assert selected and selected["quantity"] == 3, "LangGraph follow-up memory did not preserve the selected product."
        print("PASS [phase4]: multi-turn selected-product memory")

    def verify_langflow(self) -> None:
        session = requests.Session()
        login = session.get(f"{self.langflow_url}/api/v1/auto_login", timeout=30)
        login.raise_for_status()
        session.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        flows = session.get(f"{self.langflow_url}/api/v1/flows/", timeout=30)
        flows.raise_for_status()
        flow = next(item for item in flows.json() if item.get("name") == "Shop Buddy")
        assert len(flow["data"]["nodes"]) == 11 and len(flow["data"]["edges"]) == 12
        print("PASS [phase1]: LangFlow Shop Buddy flow is registered with 11 nodes and 12 edges")

        if self.has_ai_key:
            run = session.post(
                f"{self.langflow_url}/api/v1/run/shop-buddy",
                json={"input_request": {
                    "input_value": "Show me office chairs.",
                    "input_type": "chat",
                    "output_type": "chat",
                    "session_id": f"langflow-smoke-{uuid.uuid4()}",
                }},
                timeout=300,
            )
            run.raise_for_status()
            assert run.json(), "LangFlow returned an empty execution result."
            print("PASS [phase1]: live LangFlow AI execution")
        else:
            print("SKIP [phase1]: live LangFlow AI execution requires OPENAI_API_KEY or GEMINI_API_KEY")

    def cleanup(self) -> None:
        for session_id in self.sessions_to_clean:
            try:
                for item in self.cart(session_id)["items"]:
                    self.request("DELETE", "/delete_product_from_cart/", json={
                        "product_id": item["product_id"], "session_id": session_id,
                    })
            except requests.RequestException:
                pass

    def run(self) -> None:
        health = self.request("GET", "/health")
        assert health["status"] == "ok"
        assert health["workflow"] == WORKFLOW_BY_PHASE[self.phase], health
        if self.phase in {"phase2", "phase3"}:
            self.verify_framework_structure()
        try:
            if self.phase in {"phase1", "phase5"}:
                self.run_phase1_or_5()
            elif self.phase == "phase2":
                self.run_agent_phase("office chairs")
            elif self.phase == "phase3":
                self.run_agent_phase("conference chairs")
            else:
                self.run_phase4()
        finally:
            self.cleanup()
        print(f"{self.phase} evaluation smoke test passed.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=WORKFLOW_BY_PHASE, required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--langflow-url", default="http://127.0.0.1:7860")
    args = parser.parse_args()
    PhaseSmokeTest(args.phase, args.api_url, args.langflow_url).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

