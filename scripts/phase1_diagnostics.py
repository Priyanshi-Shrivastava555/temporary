"""Write a redacted Phase 1 evaluator-readiness report."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import platform
import re
import sys
from typing import Any

import requests

from listening_pids import listening_pids


LANGFLOW_URL = os.getenv("LANGFLOW_URL", "http://127.0.0.1:7860").rstrip("/")
REQUIRED_ENVIRONMENT = (
    "LANGFLOW_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "ODOO_ENDPOINT",
    "ODOO_DB_NAME",
    "ODOO_ADMIN_USERNAME",
    "ODOO_ADMIN_PASSWORD",
)


def package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not installed"


def safe_process_details(process_id: int) -> str:
    proc = Path("/proc") / str(process_id)
    try:
        executable = (proc / "exe").resolve(strict=True)
    except OSError:
        executable = Path("<unavailable>")
    try:
        working_directory = (proc / "cwd").resolve(strict=True)
    except OSError:
        working_directory = Path("<unavailable>")
    try:
        command = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", errors="replace")
    except OSError:
        command = "<unavailable>"
    command = re.sub(r"(?i)(api[_-]?key[= ]+)[^ ]+", r"\1<redacted>", command)
    return f"pid={process_id}; exe={executable}; cwd={working_directory}; command={command.strip()}"


def response_summary(response: requests.Response) -> str:
    content_type = response.headers.get("content-type", "<missing>")
    return f"HTTP {response.status_code}; content-type={content_type}; final-url={response.url}"


def write_report(output: Path) -> tuple[list[str], list[str]]:
    lines = [
        "Shop Buddy Phase 1 diagnostic report",
        f"generated_utc={datetime.now(timezone.utc).isoformat()}",
        f"platform={platform.platform()}",
        f"python={sys.version.split()[0]}",
        f"langflow_package={package_version('langflow')}",
        f"lfx_package={package_version('lfx')}",
        f"langflow_url={LANGFLOW_URL}",
    ]
    failures: list[str] = []

    process_ids = listening_pids(7860) if os.name == "posix" else []
    lines.append(f"port_7860_listener_count={len(process_ids)}")
    for process_id in process_ids:
        lines.append(f"port_7860_process={safe_process_details(process_id)}")
    if os.name == "posix" and not process_ids:
        failures.append("No process is listening on TCP port 7860.")

    for name in REQUIRED_ENVIRONMENT:
        value = os.getenv(name, "").strip()
        lines.append(f"env_{name}=configured" if value else f"env_{name}=missing")

    api_key = os.getenv("LANGFLOW_API_KEY", "").strip()
    if api_key:
        fingerprint = hashlib.sha256(api_key.encode()).hexdigest()[:12]
        lines.append(f"langflow_api_key_fingerprint_sha256={fingerprint}")
    else:
        failures.append("LANGFLOW_API_KEY is missing from the environment loaded from .env.")

    session = requests.Session()
    session.headers.update({"x-api-key": api_key, "Accept": "application/json"})
    flows_payload: list[dict[str, Any]] = []
    try:
        health = requests.get(f"{LANGFLOW_URL}/health_check", timeout=15, allow_redirects=False)
        lines.append(f"health_check={response_summary(health)}")
        if not health.ok:
            failures.append(f"LangFlow health check returned HTTP {health.status_code}.")
    except requests.RequestException as exc:
        lines.append(f"health_check=connection error: {type(exc).__name__}: {exc}")
        failures.append("LangFlow health check could not connect.")

    try:
        flows = session.get(f"{LANGFLOW_URL}/api/v1/flows/", timeout=30, allow_redirects=False)
        lines.append(f"authenticated_flows={response_summary(flows)}")
        if flows.ok and "json" in flows.headers.get("content-type", "").lower():
            payload = flows.json()
            if isinstance(payload, list):
                flows_payload = payload
        else:
            failures.append(f"LANGFLOW_API_KEY authentication returned HTTP {flows.status_code}.")
    except (requests.RequestException, ValueError) as exc:
        lines.append(f"authenticated_flows=error: {type(exc).__name__}: {exc}")
        failures.append("Authenticated LangFlow flow lookup failed.")

    canonical = [flow for flow in flows_payload if flow.get("name") == "Shop_Buddy"]
    endpoints = [flow for flow in flows_payload if flow.get("endpoint_name") == "shop-buddy"]
    lines.append(f"shop_buddy_named_flow_count={len(canonical)}")
    lines.append(f"shop_buddy_endpoint_owner_count={len(endpoints)}")
    if len(canonical) == 1:
        data = canonical[0].get("data") or {}
        lines.append(f"shop_buddy_flow_id={canonical[0].get('id')}")
        lines.append(f"shop_buddy_nodes={len(data.get('nodes') or [])}")
        lines.append(f"shop_buddy_edges={len(data.get('edges') or [])}")
        if len(data.get("nodes") or []) != 11 or len(data.get("edges") or []) != 12:
            failures.append("Shop_Buddy does not have the required 11 nodes and 12 edges.")
    else:
        failures.append(f"Expected exactly one Shop_Buddy flow; found {len(canonical)}.")
    if len(endpoints) != 1 or (canonical and endpoints and canonical[0].get("id") != endpoints[0].get("id")):
        failures.append("Shop_Buddy is not the sole owner of the shop-buddy endpoint.")

    try:
        openapi = requests.get(f"{LANGFLOW_URL}/openapi.json", timeout=30, allow_redirects=False)
        lines.append(f"openapi={response_summary(openapi)}")
        paths = openapi.json().get("paths", {}) if openapi.ok else {}
        run_routes = sorted(path for path in paths if path.startswith("/api/v1/run/"))
        lines.append(f"run_routes={json.dumps(run_routes)}")
        if not any("flow_id_or_name" in path for path in run_routes):
            failures.append("LangFlow OpenAPI does not expose the flow run route.")
    except (requests.RequestException, ValueError) as exc:
        lines.append(f"openapi=error: {type(exc).__name__}: {exc}")
        failures.append("LangFlow OpenAPI inspection failed.")

    lines.append(f"readiness={'FAIL' if failures else 'PASS'}")
    for failure in failures:
        lines.append(f"failure={failure}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines, failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    _lines, failures = write_report(args.output)
    print(f"Phase 1 diagnostic report written to {args.output}")
    if failures:
        print(f"Phase 1 diagnostic readiness failed with {len(failures)} issue(s).", file=sys.stderr)
        return 1
    print("Phase 1 diagnostic readiness passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
