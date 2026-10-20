"""Inspect existing local AI workflow services without changing their state.

The report is deliberately redacted so it can be committed and shared. It is
primarily intended to run on the Linux evaluation VDI before restarting any
service, allowing us to compare a preinstalled LangFlow service with the
project-managed one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

from dotenv import dotenv_values
import requests


DEFAULT_LANGFLOW_URL = "http://127.0.0.1:7860"
DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
PACKAGE_NAMES = (
    "langflow",
    "lfx",
    "langchain",
    "langchain-core",
    "langchain-openai",
    "langchain-google-genai",
    "langgraph",
    "crewai",
    "autogen",
    "pyautogen",
    "fastapi",
    "uvicorn",
)
PROCESS_TOKENS = (
    "langflow",
    "langchain",
    "langgraph",
    "crewai",
    "autogen",
    "uvicorn",
    "shop_buddy",
    "main:app",
)
SELECTED_ENVIRONMENT = (
    "LANGFLOW_API_KEY",
    "LANGFLOW_CONFIG_DIR",
    "LANGFLOW_AUTO_LOGIN",
    "LANGFLOW_SKIP_AUTH_AUTO_LOGIN",
    "LANGFLOW_COMPONENTS_PATH",
    "WORKFLOW_MODE",
    "SHOP_BUDDY_AI_PROVIDER",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "ODOO_ENDPOINT",
    "ODOO_DB_NAME",
    "ODOO_ADMIN_USERNAME",
    "ODOO_ADMIN_PASSWORD",
)
SECRET_NAMES = {
    "LANGFLOW_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "ODOO_ADMIN_PASSWORD",
}


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def safe_url(value: str) -> str:
    """Return a URL without credentials, query parameters, or fragments."""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "configured"
    if not parsed.scheme or not parsed.netloc:
        return "configured"
    hostname = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        return "configured"
    if port:
        hostname = f"{hostname}:{port}"
    return urlunsplit((parsed.scheme, hostname, parsed.path.rstrip("/"), "", ""))


def redact_command(command: str) -> str:
    patterns = (
        r"(?i)((?:api[_-]?key|token|password|authorization)[= ]+)[^ ]+",
        r"(?i)(--(?:api-key|token|password)\s+)[^ ]+",
    )
    for pattern in patterns:
        command = re.sub(pattern, r"\1<redacted>", command)
    return command.strip()


def read_selected_environment(process_dir: Path) -> dict[str, str]:
    try:
        entries = (process_dir / "environ").read_bytes().split(b"\0")
    except (OSError, PermissionError):
        return {}
    result: dict[str, str] = {}
    for entry in entries:
        if b"=" not in entry:
            continue
        raw_name, raw_value = entry.split(b"=", 1)
        name = raw_name.decode("utf-8", errors="replace")
        if name in SELECTED_ENVIRONMENT:
            result[name] = raw_value.decode("utf-8", errors="replace")
    return result


def format_environment(environment: dict[str, str]) -> list[str]:
    lines: list[str] = []
    for name in SELECTED_ENVIRONMENT:
        value = str(environment.get(name, "") or "").strip()
        if not value:
            lines.append(f"{name}=missing")
        elif name in SECRET_NAMES:
            lines.append(f"{name}=configured; fingerprint={fingerprint(value)}")
        elif name.endswith("URL") or name.endswith("ENDPOINT"):
            lines.append(f"{name}=configured; location={safe_url(value)}")
        elif name in {"LANGFLOW_CONFIG_DIR", "LANGFLOW_COMPONENTS_PATH", "WORKFLOW_MODE", "SHOP_BUDDY_AI_PROVIDER"}:
            lines.append(f"{name}=configured; value={value}")
        else:
            lines.append(f"{name}=configured")
    return lines


def parse_listening_inodes(proc_root: Path = Path("/proc")) -> dict[str, int]:
    """Map Linux socket inode to listening TCP port."""
    result: dict[str, int] = {}
    for table in (proc_root / "net/tcp", proc_root / "net/tcp6"):
        try:
            rows = table.read_text(encoding="utf-8", errors="replace").splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            columns = row.split()
            if len(columns) < 10 or columns[3] != "0A":
                continue
            try:
                port = int(columns[1].rsplit(":", 1)[1], 16)
            except (IndexError, ValueError):
                continue
            result[columns[9]] = port
    return result


def process_ports(process_dir: Path, listening_inodes: dict[str, int]) -> list[int]:
    ports: set[int] = set()
    try:
        descriptors = list((process_dir / "fd").iterdir())
    except (OSError, PermissionError):
        return []
    for descriptor in descriptors:
        try:
            target = os.readlink(descriptor)
        except (OSError, PermissionError):
            continue
        match = re.fullmatch(r"socket:\[(\d+)\]", target)
        if match and match.group(1) in listening_inodes:
            ports.add(listening_inodes[match.group(1)])
    return sorted(ports)


def interesting_processes(proc_root: Path = Path("/proc")) -> Iterable[dict[str, Any]]:
    if not proc_root.exists():
        return
    listening_inodes = parse_listening_inodes(proc_root)
    for process_dir in proc_root.glob("[0-9]*"):
        try:
            command = (process_dir / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", errors="replace"
            )
            if not any(token in command.lower() for token in PROCESS_TOKENS):
                continue
            status = (process_dir / "status").read_text(encoding="utf-8", errors="replace")
            parent_match = re.search(r"^PPid:\s+(\d+)", status, re.MULTILINE)
            parent_id = int(parent_match.group(1)) if parent_match else 0
            try:
                executable = str((process_dir / "exe").resolve(strict=True))
            except OSError:
                executable = "unavailable"
            try:
                working_directory = str((process_dir / "cwd").resolve(strict=True))
            except OSError:
                working_directory = "unavailable"
            yield {
                "pid": int(process_dir.name),
                "ppid": parent_id,
                "command": redact_command(command),
                "executable": executable,
                "cwd": working_directory,
                "ports": process_ports(process_dir, listening_inodes),
                "environment": read_selected_environment(process_dir),
            }
        except (OSError, PermissionError, ValueError):
            continue


def python_package_versions(python: Path) -> dict[str, str]:
    code = (
        "import importlib.metadata as m,json;"
        f"names={list(PACKAGE_NAMES)!r};"
        "print(json.dumps({n:(m.version(n) if n in {d.metadata.get('Name','').lower() "
        "for d in m.distributions()} else 'not installed') for n in names}))"
    )
    try:
        completed = subprocess.run(
            [str(python), "-c", code],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"inspection_error": type(exc).__name__}
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()[-1:] or [f"exit {completed.returncode}"]
        return {"inspection_error": redact_command(detail[0])}
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"inspection_error": "invalid JSON from interpreter"}


def request_summary(
    session: requests.Session,
    url: str,
    api_key: str | None = None,
    timeout: int = 30,
) -> tuple[str, requests.Response | None]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    try:
        response = session.get(url, headers=headers, timeout=timeout, allow_redirects=False)
    except requests.RequestException as exc:
        return f"connection-error:{type(exc).__name__}", None
    content_type = response.headers.get("content-type", "missing").split(";", 1)[0]
    return f"HTTP-{response.status_code}; content-type={content_type}", response


def json_body(response: requests.Response | None) -> Any | None:
    if response is None:
        return None
    try:
        return response.json()
    except (requests.JSONDecodeError, ValueError):
        return None


def openapi_paths(document: Any) -> list[str]:
    if not isinstance(document, dict) or not isinstance(document.get("paths"), dict):
        return []
    return sorted(str(path) for path in document["paths"])


def flow_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("flows", "data", "items"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
    return []


def flow_size(flow: dict[str, Any]) -> tuple[int, int]:
    data = flow.get("data", {})
    if not isinstance(data, dict):
        return 0, 0
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    return len(nodes) if isinstance(nodes, list) else 0, len(edges) if isinstance(edges, list) else 0


def component_summary(payload: Any) -> tuple[int, list[str]]:
    if not isinstance(payload, dict):
        return 0, []
    names: set[str] = set()
    total = 0
    for category, value in payload.items():
        if isinstance(value, dict):
            total += len(value)
            names.add(str(category))
        elif isinstance(value, list):
            total += len(value)
            names.add(str(category))
    return total, sorted(names)


def inspect_http_service(
    lines: list[str],
    label: str,
    base_url: str,
    key_candidates: dict[str, str],
) -> dict[str, Any]:
    lines.append(f"[{label} HTTP service: {base_url}]")
    session = requests.Session()
    result: dict[str, Any] = {"reachable": False, "paths": [], "working_key": None}

    for path in ("/health", "/openapi.json"):
        summary, response = request_summary(session, f"{base_url}{path}")
        lines.append(f"GET {path} without-key={summary}")
        if response is not None:
            result["reachable"] = True
        if path == "/openapi.json":
            paths = openapi_paths(json_body(response))
            result["paths"] = paths
            lines.append(f"openapi_path_count={len(paths)}")
            for route in paths:
                lines.append(f"openapi_path={route}")

    if label != "LangFlow":
        return result

    summary, response = request_summary(session, f"{base_url}/api/v1/flows/")
    lines.append(f"GET /api/v1/flows/ without-key={summary}")
    successful_response = response if response is not None and response.status_code == 200 else None
    if successful_response is not None:
        result["working_key"] = "no key required"

    already_probed: set[str] = set()
    for source, api_key in key_candidates.items():
        digest = fingerprint(api_key)
        if digest in already_probed:
            continue
        already_probed.add(digest)
        summary, keyed_response = request_summary(
            session, f"{base_url}/api/v1/flows/", api_key=api_key
        )
        lines.append(f"GET /api/v1/flows/ key-{digest} ({source})={summary}")
        if keyed_response is not None and keyed_response.status_code == 200:
            successful_response = keyed_response
            result["working_key"] = digest

    records = flow_records(json_body(successful_response))
    lines.append(f"visible_flow_count={len(records)}")
    for flow in records:
        name = str(flow.get("name") or flow.get("display_name") or "unnamed")
        endpoint = str(flow.get("endpoint_name") or flow.get("id") or "missing")
        nodes, edges = flow_size(flow)
        lines.append(
            f"flow=name:{name}; endpoint:{endpoint}; nodes:{nodes}; edges:{edges}"
        )

    component_key = None
    if isinstance(result["working_key"], str) and result["working_key"] != "no key required":
        component_key = next(
            (value for value in key_candidates.values() if fingerprint(value) == result["working_key"]),
            None,
        )
    if not result["paths"] and component_key is not None:
        summary, openapi_response = request_summary(
            session, f"{base_url}/openapi.json", api_key=component_key
        )
        lines.append(f"GET /openapi.json authenticated={summary}")
        result["paths"] = openapi_paths(json_body(openapi_response))
        lines.append(f"authenticated_openapi_path_count={len(result['paths'])}")
        for route in result["paths"]:
            lines.append(f"openapi_path={route}")

    summary, components_response = request_summary(
        session,
        f"{base_url}/api/v1/all",
        api_key=component_key,
        timeout=90,
    )
    lines.append(f"GET /api/v1/all={summary}")
    component_count, categories = component_summary(json_body(components_response))
    lines.append(f"available_component_count={component_count}")
    lines.append(f"component_categories={','.join(categories) if categories else 'unavailable'}")

    paths = result["paths"]
    capability_patterns = {
        "flow-management": ("/flows",),
        "flow-execution": ("/run/",),
        "component-catalog": ("/all", "/components"),
        "api-key-management": ("api_key", "api-key"),
        "project-management": ("/projects",),
        "variables": ("/variables",),
        "monitoring": ("/monitor",),
    }
    for capability, patterns in capability_patterns.items():
        available = any(any(pattern in path for pattern in patterns) for path in paths)
        lines.append(f"capability_{capability}={'yes' if available else 'no'}")
    return result


def candidate_interpreters(project_root: Path, processes: list[dict[str, Any]]) -> list[Path]:
    candidates = [
        project_root / ".langflow-venv/bin/python",
        project_root / ".langflow-venv/bin/python3",
        Path("/Software/langenv/bin/python3"),
        Path("/Software/langenv/bin/python"),
        Path(sys.executable),
    ]
    candidates.extend(
        Path(process["executable"])
        for process in processes
        if process["executable"] != "unavailable"
        and "python" in Path(process["executable"]).name.lower()
    )
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate)
        if normalized not in seen and candidate.exists():
            seen.add(normalized)
            unique.append(candidate)
    return unique


def recommendation(
    project_root: Path,
    processes: list[dict[str, Any]],
    langflow: dict[str, Any],
) -> list[str]:
    lines = ["[reuse/update assessment]"]
    listeners = [process for process in processes if 7860 in process["ports"]]
    if not listeners:
        lines.append("status=no process could be mapped to TCP port 7860")
        lines.append("action=start the intended LangFlow service, then rerun this collector")
        return lines

    project_owned = any(str(project_root) in process["cwd"] for process in listeners)
    global_owned = any("/Software/langenv" in process["executable"] for process in listeners)
    lines.append(f"listener_7860_count={len(listeners)}")
    lines.append(f"project_managed_listener={'yes' if project_owned else 'no'}")
    lines.append(f"preinstalled_global_listener={'yes' if global_owned else 'no'}")

    if langflow.get("working_key"):
        lines.append(f"authenticated_flow_access=yes; credential={langflow['working_key']}")
    else:
        lines.append("authenticated_flow_access=no")
    has_run = any("/run/" in path for path in langflow.get("paths", []))
    lines.append(f"flow_execution_route={'yes' if has_run else 'no'}")

    if project_owned and langflow.get("working_key") and has_run:
        lines.append("reuse_decision=current project-managed LangFlow is technically reusable")
        lines.append(
            "important=evaluator authentication can still fail when its process does not receive the matching LANGFLOW_API_KEY"
        )
    elif global_owned:
        lines.append(
            "reuse_decision=preinstalled LangFlow should only be reused after its version, authentication, and flow ownership match the report"
        )
    else:
        lines.append("reuse_decision=do not update or replace the listener until its owner is identified")
    lines.append("mutation_performed=no; this collector is read-only")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--output", type=Path, default=Path("existing_ai_services_report.txt"))
    parser.add_argument("--langflow-url", default=DEFAULT_LANGFLOW_URL)
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    environment = {
        name: str(value or "")
        for name, value in dotenv_values(args.env_file).items()
        if name in SELECTED_ENVIRONMENT
    }
    key_candidates: dict[str, str] = {}
    if environment.get("LANGFLOW_API_KEY", "").strip():
        key_candidates["project-env"] = environment["LANGFLOW_API_KEY"].strip()

    processes = list(interesting_processes())
    for process in processes:
        api_key = process["environment"].get("LANGFLOW_API_KEY", "").strip()
        if api_key:
            key_candidates[f"process-{process['pid']}"] = api_key

    lines = [
        "Shop Buddy existing AI service capability report (redacted)",
        f"platform={platform.platform()}",
        f"collector_python={sys.version.split()[0]}",
        f"project_root={project_root}",
        "scope=read-only; no services were started, stopped, registered, or updated",
        "[project environment]",
    ]
    lines.extend(format_environment(environment))

    lines.append("[running AI-related processes]")
    lines.append(f"process_count={len(processes)}")
    for process in processes:
        lines.append(
            "process="
            f"pid:{process['pid']}; ppid:{process['ppid']}; ports:{process['ports'] or 'none'}; "
            f"executable:{process['executable']}; cwd:{process['cwd']}; command:{process['command']}"
        )
        for detail in format_environment(process["environment"]):
            if not detail.endswith("=missing"):
                lines.append(f"process_env_{process['pid']}_{detail}")

    lines.append("[relevant Python environments]")
    for python in candidate_interpreters(project_root, processes):
        lines.append(f"interpreter={python}")
        versions = python_package_versions(python)
        for package, package_version in versions.items():
            lines.append(f"package_{package}={package_version}")

    langflow_result = inspect_http_service(
        lines, "LangFlow", args.langflow_url.rstrip("/"), key_candidates
    )
    inspect_http_service(lines, "Shop Buddy backend", args.backend_url.rstrip("/"), {})
    lines.extend(recommendation(project_root, processes, langflow_result))

    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Redacted AI service capability report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
