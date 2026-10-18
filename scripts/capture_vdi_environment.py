"""Capture redacted VDI evaluator/LangFlow environment diagnostics."""
from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import PackageNotFoundError, version
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from typing import Iterable

from dotenv import dotenv_values
import requests


LANGFLOW_URL = "http://127.0.0.1:7860"
INTERESTING_COMMANDS = ("langflow", "evaluat", "grader", "assessment", "tekstac")
SELECTED_ENVIRONMENT = (
    "LANGFLOW_API_KEY",
    "LANGFLOW_CONFIG_DIR",
    "LANGFLOW_AUTO_LOGIN",
    "LANGFLOW_SKIP_AUTH_AUTO_LOGIN",
    "OPENAI_BASE_URL",
)


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def redact_command(command: str) -> str:
    command = re.sub(r"(?i)(api[_-]?key[= ]+)[^ ]+", r"\1<redacted>", command)
    command = re.sub(r"(?i)(authorization[= ]+)[^ ]+", r"\1<redacted>", command)
    return command.strip()


def read_process_environment(process_dir: Path) -> dict[str, str]:
    try:
        entries = (process_dir / "environ").read_bytes().split(b"\0")
    except (OSError, PermissionError):
        return {}
    result: dict[str, str] = {}
    for entry in entries:
        if b"=" not in entry:
            continue
        name, value = entry.split(b"=", 1)
        decoded_name = name.decode("utf-8", errors="replace")
        if decoded_name in SELECTED_ENVIRONMENT:
            result[decoded_name] = value.decode("utf-8", errors="replace")
    return result


def format_selected_environment(environment: dict[str, str], key_candidates: dict[str, str], source: str) -> list[str]:
    lines: list[str] = []
    for name in SELECTED_ENVIRONMENT:
        value = environment.get(name, "").strip()
        if name == "LANGFLOW_API_KEY" and value:
            digest = fingerprint(value)
            lines.append(f"{name}=configured; fingerprint={digest}")
            key_candidates[f"{source}:{digest}"] = value
        elif value:
            lines.append(f"{name}=configured")
        else:
            lines.append(f"{name}=missing")
    return lines


def interesting_processes(proc_root: Path = Path("/proc")) -> Iterable[tuple[int, int, str, Path]]:
    for process_dir in proc_root.glob("[0-9]*"):
        try:
            process_id = int(process_dir.name)
            status = (process_dir / "status").read_text(encoding="utf-8", errors="replace")
            parent_match = re.search(r"^PPid:\s+(\d+)", status, re.MULTILINE)
            parent_id = int(parent_match.group(1)) if parent_match else 0
            command = (process_dir / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", errors="replace"
            )
        except (OSError, PermissionError, ValueError):
            continue
        if any(token in command.lower() for token in INTERESTING_COMMANDS):
            yield process_id, parent_id, redact_command(command), process_dir


def systemd_user_environment() -> dict[str, str]:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show-environment"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    environment: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name in SELECTED_ENVIRONMENT:
            environment[name] = value
    return environment


def probe_key(label: str, api_key: str | None) -> str:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    try:
        response = requests.get(
            f"{LANGFLOW_URL}/api/v1/flows/",
            headers=headers,
            timeout=20,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        return f"probe_{label}=connection-error:{type(exc).__name__}"
    content_type = response.headers.get("content-type", "<missing>")
    return f"probe_{label}=HTTP-{response.status_code}; content-type={content_type}"


def global_langflow_version() -> str:
    python = Path("/Software/langenv/bin/python3")
    if not python.exists():
        return "not present"
    try:
        result = subprocess.run(
            [str(python), "-c", "from importlib.metadata import version; print(version('langflow'))"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"error:{type(exc).__name__}"
    return result.stdout.strip() or f"error:exit-{result.returncode}"


def local_package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not installed"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    lines = [
        "Shop Buddy VDI evaluator environment diagnostics (redacted)",
        f"platform={platform.platform()}",
        f"python={sys.version.split()[0]}",
        f"current_uid={os.getuid() if hasattr(os, 'getuid') else 'n/a'}",
        f"local_langflow_package={local_package_version('langflow')}",
        f"global_langflow_package={global_langflow_version()}",
    ]
    key_candidates: dict[str, str] = {}

    persisted = {name: str(value or "") for name, value in dotenv_values(args.env_file).items()}
    lines.append("[project .env]")
    lines.extend(format_selected_environment(persisted, key_candidates, "project-env"))

    current = {name: os.getenv(name, "") for name in SELECTED_ENVIRONMENT}
    lines.append("[capture process environment]")
    lines.extend(format_selected_environment(current, key_candidates, "capture-process"))

    user_manager = systemd_user_environment()
    lines.append("[systemd user-manager environment]")
    lines.extend(format_selected_environment(user_manager, key_candidates, "systemd-user"))

    lines.append("[interesting processes]")
    process_count = 0
    for process_id, parent_id, command, process_dir in interesting_processes():
        process_count += 1
        lines.append(f"process=pid:{process_id}; ppid:{parent_id}; command:{command}")
        process_environment = read_process_environment(process_dir)
        for detail in format_selected_environment(
            process_environment, key_candidates, f"process-{process_id}"
        ):
            lines.append(f"process_env_{process_id}_{detail}")
    lines.append(f"interesting_process_count={process_count}")

    for startup_file in (Path.home() / ".profile", Path.home() / ".bash_profile", Path.home() / ".bashrc"):
        try:
            contains_name = "LANGFLOW_API_KEY" in startup_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            contains_name = False
        lines.append(f"startup_file_{startup_file.name}_mentions_LANGFLOW_API_KEY={'yes' if contains_name else 'no'}")

    lines.append("[authentication probes]")
    lines.append(probe_key("without-key", None))
    probed_fingerprints: set[str] = set()
    for source, api_key in key_candidates.items():
        digest = fingerprint(api_key)
        if digest in probed_fingerprints:
            continue
        probed_fingerprints.add(digest)
        lines.append(probe_key(f"fingerprint-{digest}", api_key))
        lines.append(f"fingerprint_{digest}_sources={','.join(k for k, v in key_candidates.items() if v == api_key)}")

    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Redacted VDI environment diagnostics written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
