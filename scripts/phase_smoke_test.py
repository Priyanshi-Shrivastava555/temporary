"""Evaluation-oriented smoke tests for the five Shop Buddy phase profiles."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import time
import traceback
import uuid
from typing import Any

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    # Direct execution (``python scripts/phase_smoke_test.py``) otherwise puts
    # only the scripts directory on sys.path on some Python/OS combinations.
    # Phase 2/3 structure checks import the local package explicitly.
    sys.path.insert(0, str(PROJECT_ROOT))


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
        self.current_check = "initialization"
        self.active_provider = os.getenv("SHOP_BUDDY_ACTIVE_AI_PROVIDER", "").strip().lower()
        if self.active_provider:
            self.has_ai_key = self.active_provider in {"openai", "gemini"}
        else:
            # Preserve direct invocation outside the launcher.
            self.has_ai_key = bool(os.getenv("OPENAI_API_KEY") or os.getenv("GEMINI_API_KEY"))

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.api_url}{path}"
        self.current_check = f"FastAPI {method.upper()} {path}"
        try:
            response = requests.request(method, url, timeout=kwargs.pop("timeout", 120), **kwargs)
        except requests.RequestException as exc:
            raise RuntimeError(
                f"[{self.phase}] {self.current_check} could not connect to {url}: {type(exc).__name__}: {exc}"
            ) from exc
        if not response.ok:
            raise RuntimeError(
                f"[{self.phase}] {self.current_check} failed with HTTP {response.status_code}. "
                f"Response: {self.response_detail(response)}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"[{self.phase}] {self.current_check} returned invalid JSON. Response: {response.text[:1500]}"
            ) from exc

    @staticmethod
    def response_detail(response: requests.Response) -> str:
        try:
            content = json.dumps(response.json(), default=str)
        except ValueError:
            content = response.text
        return " ".join(content.split())[:2000] or "<empty response body>"

    @classmethod
    def require_json_response(cls, response: requests.Response, operation: str) -> dict[str, Any]:
        """Return a non-empty JSON object or raise with transport-level diagnostics."""
        content_type = response.headers.get("content-type", "<missing>")
        content_length = response.headers.get("content-length", "<missing>")
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"{operation} returned HTTP {response.status_code} but not JSON "
                f"(content-type={content_type!r}, content-length={content_length!r}). "
                f"Response: {cls.response_detail(response)}"
            ) from exc
        if not isinstance(payload, dict) or not payload:
            raise RuntimeError(
                f"{operation} returned HTTP {response.status_code} without a non-empty JSON object "
                f"(content-type={content_type!r}, content-length={content_length!r}). "
                f"Response: {cls.response_detail(response)}"
            )
        return payload

    @staticmethod
    def redact(text: str) -> str:
        for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "ODOO_ADMIN_PASSWORD"):
            secret = os.getenv(name, "")
            if secret:
                text = text.replace(secret, f"<{name}:redacted>")
        text = re.sub(r"(?i)(authorization[^\n:]*:\s*bearer\s+)[^\s]+", r"\1<redacted>", text)
        text = re.sub(r"(?i)(api[_-]?key[\"'=:\s]+)[A-Za-z0-9._-]{8,}", r"\1<redacted>", text)
        return text

    def failure_report(self, exc: BaseException) -> None:
        print("\n" + "=" * 78, file=sys.stderr)
        print(f"SHOP BUDDY SMOKE FAILURE [{self.phase}]", file=sys.stderr)
        print(f"Check: {self.current_check}", file=sys.stderr)
        print(f"Error: {type(exc).__name__}: {self.redact(str(exc))}", file=sys.stderr)
        print("Traceback:", file=sys.stderr)
        print(self.redact(traceback.format_exc()).rstrip(), file=sys.stderr)
        log_names = ["api-error.log", "api.log"]
        if self.phase == "phase1":
            log_names = ["langflow-error.log", "langflow.log", *log_names]
        logs_dir = Path.cwd() / "logs"
        for name in log_names:
            path = logs_dir / name
            if not path.exists():
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]
            except OSError as log_error:
                print(f"\n--- {path} could not be read: {log_error} ---", file=sys.stderr)
                continue
            print(f"\n--- last {len(lines)} lines: {path} ---", file=sys.stderr)
            print(self.redact("\n".join(lines)) or "<log is empty>", file=sys.stderr)
        print("=" * 78, file=sys.stderr)

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
        self.current_check = f"{self.phase} framework structure"
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
        self.current_check = "LangFlow authentication"
        session = requests.Session()
        login = session.get(f"{self.langflow_url}/api/v1/auto_login", timeout=30)
        if not login.ok:
            raise RuntimeError(
                f"LangFlow GET /api/v1/auto_login failed with HTTP {login.status_code}. "
                f"Response: {self.response_detail(login)}"
            )
        session.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        self.current_check = "LangFlow registered-flow lookup"
        flows = session.get(f"{self.langflow_url}/api/v1/flows/", timeout=30)
        if not flows.ok:
            raise RuntimeError(
                f"LangFlow GET /api/v1/flows/ failed with HTTP {flows.status_code}. "
                f"Response: {self.response_detail(flows)}"
            )
        all_flows = flows.json()
        named_flows = [item for item in all_flows if item.get("name") == "Shop_Buddy"]
        endpoint_flows = [item for item in all_flows if item.get("endpoint_name") == "shop-buddy"]
        assert len(named_flows) == 1, f"Expected one Shop_Buddy flow, found {[item.get('id') for item in named_flows]}"
        assert len(endpoint_flows) == 1, (
            f"Expected one shop-buddy endpoint owner, found {[item.get('id') for item in endpoint_flows]}"
        )
        flow = named_flows[0]
        assert flow.get("id") == endpoint_flows[0].get("id"), "Shop_Buddy does not own the shop-buddy endpoint."
        assert len(flow["data"]["nodes"]) == 11 and len(flow["data"]["edges"]) == 12
        model_edges = [
            edge for edge in flow["data"]["edges"]
            if (edge.get("data") or {}).get("targetHandle", {}).get("fieldName") == "model"
        ]
        assert {edge.get("target") for edge in model_edges} == {
            "Agent-orchestrator", "Agent-search", "Agent-cart",
        }, f"Invalid Agent model connections: {model_edges}"
        print("PASS [phase1]: LangFlow Shop_Buddy flow is registered with 11 nodes and 12 edges")

        if self.has_ai_key:
            self.current_check = f"LangFlow live Shop Buddy execution ({self.active_provider or 'configured provider'})"
            run = None
            for attempt in range(2):
                run = session.post(
                    # Exercise the same stable endpoint the evaluator uses.
                    # SimplifiedAPIRequest fields belong at the JSON root in
                    # LangFlow 1.12; wrapping them in ``input_request`` causes
                    # LangFlow to silently discard the prompt and session ID.
                    f"{self.langflow_url}/api/v1/run/shop-buddy",
                    json={
                        "input_value": "Show me office chairs.",
                        "input_type": "chat",
                        "output_type": "chat",
                        "session_id": f"langflow-smoke-{uuid.uuid4()}",
                    },
                    headers={"Accept": "application/json"},
                    timeout=300,
                )
                if run.status_code < 500 or attempt == 1:
                    break
                time.sleep(2)
            assert run is not None
            if not run.ok:
                detail = self.response_detail(run)
                provider = self.active_provider or "configured provider"
                raise RuntimeError(
                    f"LangFlow Shop_Buddy execution failed with HTTP {run.status_code} using {provider}: {detail}. "
                    "The services remain running; inspect logs/langflow-error.log for the component traceback."
                )
            result = self.require_json_response(run, "LangFlow Shop_Buddy execution")
            if not isinstance(result.get("outputs"), list):
                raise RuntimeError(
                    "LangFlow Shop_Buddy execution returned JSON without the expected 'outputs' list. "
                    f"Response: {self.response_detail(run)}"
                )
            print(f"PASS [phase1]: live LangFlow AI execution using {self.active_provider or 'configured provider'}")
        else:
            print("SKIP [phase1]: live LangFlow AI execution requires OPENAI_API_KEY or GEMINI_API_KEY")

    def cleanup(self) -> None:
        for session_id in self.sessions_to_clean:
            try:
                for item in self.cart(session_id)["items"]:
                    self.request("DELETE", "/delete_product_from_cart/", json={
                        "product_id": item["product_id"], "session_id": session_id,
                    })
            except (requests.RequestException, RuntimeError):
                pass

    def run(self) -> None:
        self.current_check = "FastAPI health and workflow mode"
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
            previous_check = self.current_check
            self.cleanup()
            self.current_check = previous_check
        print(f"{self.phase} evaluation smoke test passed.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=WORKFLOW_BY_PHASE, required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--langflow-url", default="http://127.0.0.1:7860")
    args = parser.parse_args()
    smoke = PhaseSmokeTest(args.phase, args.api_url, args.langflow_url)
    try:
        smoke.run()
    except Exception as exc:
        smoke.failure_report(exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

