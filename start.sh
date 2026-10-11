#!/usr/bin/env bash

set -Eeuo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_root"

phase="phase1"
phase_requested=false
no_install=false
run_smoke=false
stop_only=false
api_only=false

usage() {
    cat <<'EOF'
Usage:
  ./start.sh --phase1 [--api-only] [--no-install]   LangFlow + FastAPI + Phase 1 smoke test
  ./start.sh --phase2 [--api-only] [--no-install]   CrewAI + FastAPI + Phase 2 smoke test
  ./start.sh --phase3 [--no-install]   AutoGen + FastAPI + React + Phase 3 smoke test
  ./start.sh --phase4 [--no-install]   LangGraph + FastAPI + React + Phase 4 smoke test
  ./start.sh --phase5 [--no-install]   Deployment-readiness profile + Phase 5 smoke test
  ./start.sh --stop                     Stop services started by this launcher

With no phase argument, Phase 1 services start without automatically running the smoke test.
EOF
}

for argument in "$@"; do
    case "$argument" in
        --phase1|--phase2|--phase3|--phase4|--phase5)
            if [[ "$phase_requested" == true ]]; then
                echo "Select only one phase." >&2
                exit 2
            fi
            phase="${argument#--}"
            phase_requested=true
            run_smoke=true
            ;;
        --smoke-test) run_smoke=true ;;
        --no-install) no_install=true ;;
        --api-only) api_only=true ;;
        --stop) stop_only=true ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $argument" >&2; usage; exit 2 ;;
    esac
done

stop_pid_file() {
    local service_name="$1"
    local pid_file="$project_root/logs/$service_name.pid"
    [[ -f "$pid_file" ]] || return 0

    local process_id
    process_id="$(tr -cd '0-9' < "$pid_file")"
    if [[ -z "$process_id" || "$process_id" == "$$" ]]; then
        rm -f "$pid_file"
        return 0
    fi

    if kill -0 "$process_id" 2>/dev/null; then
        local process_cwd=""
        process_cwd="$(readlink -f "/proc/$process_id/cwd" 2>/dev/null || true)"
        if [[ "$process_cwd" == "$project_root"* ]]; then
            echo "Stopping $service_name (PID $process_id)..."
            kill -TERM -- "-$process_id" 2>/dev/null || kill -TERM "$process_id" 2>/dev/null || true
            for _attempt in $(seq 1 20); do
                kill -0 "$process_id" 2>/dev/null || break
                sleep 0.25
            done
        else
            echo "Not stopping stale $service_name PID $process_id because it is outside this project." >&2
        fi
    fi
    rm -f "$pid_file"
}

stop_all() {
    stop_pid_file langflow
    stop_pid_file frontend
    stop_pid_file api
    rm -f "$project_root/logs/active-phase"
}

if [[ "$stop_only" == true ]]; then
    stop_all
    echo "Shop Buddy services have been stopped."
    exit 0
fi

if [[ "$phase_requested" == true ]]; then
    stop_all
fi

case "$phase" in
    phase1) workflow_mode="langgraph"; needs_langflow=true ;;
    phase2) workflow_mode="crewai"; needs_langflow=false ;;
    phase3) workflow_mode="autogen"; needs_langflow=false ;;
    phase4|phase5) workflow_mode="langgraph"; needs_langflow=false ;;
esac

if [[ "$phase" == "phase5" && "$api_only" == true ]]; then
    echo "Phase 5 includes frontend deployment readiness and cannot use --api-only." >&2
    exit 2
fi

required_commands=(python3 setsid)
if [[ "$api_only" == false ]]; then
    required_commands+=(node npm)
fi
for command_name in "${required_commands[@]}"; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "$command_name was not found in PATH. See the Linux setup section in README.md." >&2
        exit 1
    fi
done

python3 -c 'import sys; assert (3, 11) <= sys.version_info[:2] < (3, 13), "Shop Buddy requires Python 3.11 or 3.12"'
if [[ "$api_only" == false ]]; then
    node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (!((major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22)) { console.error("Shop Buddy requires Node 20.19+ or Node 22.12+"); process.exit(1); }'
fi

venv_python="$project_root/.venv/bin/python"
if [[ ! -x "$venv_python" ]]; then
    if [[ "$no_install" == true ]]; then
        echo ".venv is missing; run this phase once without --no-install." >&2
        exit 1
    fi
    echo "Creating local Python environment..."
    python3 -m venv "$project_root/.venv"
fi

langflow_python="$project_root/.langflow-venv/bin/python"
if [[ "$needs_langflow" == true && ! -x "$langflow_python" ]]; then
    if [[ "$no_install" == true ]]; then
        echo ".langflow-venv is missing; run Phase 1 once without --no-install." >&2
        exit 1
    fi
    echo "Creating isolated LangFlow environment..."
    python3 -m venv "$project_root/.langflow-venv"
fi

if [[ "$no_install" == true ]]; then
    if ! "$venv_python" -c 'import fastapi, requests, langgraph, crewai, autogen' >/dev/null 2>&1; then
        echo "The application environment is incomplete. Run ./start.sh --$phase once without --no-install." >&2
        exit 1
    fi
    if [[ "$api_only" == false && ! -x "$project_root/frontend/node_modules/.bin/vite" ]]; then
        echo "Frontend dependencies are missing. Run ./start.sh --$phase once without --no-install." >&2
        exit 1
    fi
    if [[ "$needs_langflow" == true ]] && ! "$langflow_python" -c 'import langflow, requests' >/dev/null 2>&1; then
        echo "The LangFlow environment is incomplete. Run ./start.sh --phase1 once without --no-install." >&2
        exit 1
    fi
fi

if [[ "$no_install" == false ]]; then
    echo "Installing/verifying the complete backend environment..."
    "$venv_python" -m pip install --upgrade pip
    "$venv_python" -m pip install -r "$project_root/requirements.txt"
    if [[ "$api_only" == false ]]; then
        (cd "$project_root/frontend" && npm install)
    fi

    if [[ "$needs_langflow" == true ]]; then
        if ! "$langflow_python" -c 'from importlib.metadata import version; assert version("langflow") == "1.12.5"' >/dev/null 2>&1; then
            echo "Installing LangFlow 1.12.5 (the first installation can take several minutes)..."
            "$langflow_python" -m pip install --upgrade pip
            "$langflow_python" -m pip install -r "$project_root/requirements-langflow.txt"
        else
            echo "LangFlow 1.12.5 is already installed."
        fi
    fi
fi

if [[ "$phase" == "phase5" ]]; then
    echo "Building the production React bundle for the deployment-readiness check..."
    (cd "$project_root/frontend" && npm run build)
fi

if [[ ! -f "$project_root/.env" ]]; then
    cp "$project_root/.env.example" "$project_root/.env"
fi
mkdir -p "$project_root/logs"

set -a
# shellcheck disable=SC1091
. "$project_root/.env"
set +a

export SHOP_BUDDY_WORKFLOW_OVERRIDE="$workflow_mode"
export LANGFLOW_COMPONENTS_PATH="$project_root/langflow/components"
export LANGFLOW_CONFIG_DIR="$project_root/.langflow-data"
export LANGFLOW_AUTO_LOGIN="true"
export LANGFLOW_CORS_ORIGINS="http://127.0.0.1:7860,http://localhost:7860"
export DO_NOT_TRACK="true"
export XDG_DATA_HOME="$project_root/.runtime-data"
export CREWAI_STORAGE_DIR="shop_buddy"
mkdir -p "$XDG_DATA_HOME"

if [[ -z "${OPENAI_API_KEY:-}" && -z "${GEMINI_API_KEY:-}" ]]; then
    echo "WARNING: no OpenAI or Gemini key is configured. Deterministic shopping operations will be tested,"
    echo "         but live AI execution for $phase cannot be verified until a valid key is added to .env."
fi
if [[ -z "${ODOO_ENDPOINT:-}" || -z "${ODOO_DB_NAME:-}" || -z "${ODOO_ADMIN_USERNAME:-}" || -z "${ODOO_ADMIN_PASSWORD:-}" ]]; then
    echo "INFO: Odoo credentials are incomplete; the approved SQLite implementation will be used."
fi

port_open() {
    "$venv_python" -c 'import socket, sys; sock = socket.socket(); sock.settimeout(0.3); result = sock.connect_ex(("127.0.0.1", int(sys.argv[1]))); sock.close(); raise SystemExit(0 if result == 0 else 1)' "$1"
}

if ! port_open 8000; then
    echo "Starting FastAPI in $workflow_mode mode..."
    nohup setsid "$venv_python" -m uvicorn main:app --host 127.0.0.1 --port 8000 \
        >"$project_root/logs/api.log" 2>"$project_root/logs/api-error.log" &
    echo $! >"$project_root/logs/api.pid"
fi

if [[ "$api_only" == false ]] && ! port_open 5173; then
    echo "Starting React frontend..."
    (
        cd "$project_root/frontend"
        nohup setsid npm run dev -- --host 127.0.0.1 --port 5173 \
            >"$project_root/logs/frontend.log" 2>"$project_root/logs/frontend-error.log" &
        echo $! >"$project_root/logs/frontend.pid"
    )
fi

if [[ "$needs_langflow" == true ]] && ! port_open 7860; then
    echo "Starting LangFlow (initial component loading can take a few minutes)..."
    nohup setsid "$langflow_python" -m langflow run --host 127.0.0.1 --port 7860 \
        >"$project_root/logs/langflow.log" 2>"$project_root/logs/langflow-error.log" &
    echo $! >"$project_root/logs/langflow.pid"
fi

services_ready() {
    port_open 8000 \
        && { [[ "$api_only" == true ]] || port_open 5173; } \
        && { [[ "$needs_langflow" == false ]] || port_open 7860; }
}

wait_limit=90
[[ "$needs_langflow" == true ]] && wait_limit=420
for attempt in $(seq 1 "$wait_limit"); do
    services_ready && break
    if (( attempt % 20 == 0 )); then
        echo "Waiting for the $phase services to become ready..."
    fi
    sleep 1
done

if ! port_open 8000; then echo "FastAPI did not start. Check logs/api-error.log." >&2; exit 1; fi
if [[ "$api_only" == false ]] && ! port_open 5173; then echo "React did not start. Check logs/frontend-error.log." >&2; exit 1; fi
if [[ "$needs_langflow" == true ]] && ! port_open 7860; then
    echo "LangFlow did not start. Check logs/langflow-error.log." >&2
    exit 1
fi

"$venv_python" -c 'import json, sys, urllib.request; response = json.load(urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5)); assert response.get("status") == "ok", response; assert response.get("workflow") == sys.argv[1], response' "$workflow_mode"

if [[ "$needs_langflow" == true ]]; then
    "$langflow_python" "$project_root/scripts/register_langflow_flow.py"
fi

echo "$phase" >"$project_root/logs/active-phase"

if [[ "$run_smoke" == true ]]; then
    "$venv_python" "$project_root/scripts/phase_smoke_test.py" --phase "$phase"
fi

echo
echo "Shop Buddy $phase is ready."
if [[ "$api_only" == false ]]; then
    echo "  Storefront: http://127.0.0.1:5173"
else
    echo "  Storefront: skipped (--api-only)"
fi
echo "  API docs:   http://127.0.0.1:8000/docs"
if [[ "$needs_langflow" == true ]]; then
    echo "  LangFlow:   http://127.0.0.1:7860"
fi
echo "  Stop:       ./start.sh --stop"
echo "  Logs:       $project_root/logs/"

