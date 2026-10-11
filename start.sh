#!/usr/bin/env bash

set -Eeuo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_root"

no_install=false
for argument in "$@"; do
    case "$argument" in
        --no-install) no_install=true ;;
        -h|--help)
            echo "Usage: ./start.sh [--no-install]"
            echo "Starts the FastAPI backend and React frontend on localhost."
            exit 0
            ;;
        *)
            echo "Unknown option: $argument" >&2
            exit 2
            ;;
    esac
done

for command_name in python3 node npm; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "$command_name was not found in PATH. See the Linux setup section in README.md." >&2
        exit 1
    fi
done

python3 -c 'import sys; assert (3, 11) <= sys.version_info[:2] < (3, 13), "Shop Buddy requires Python 3.11 or 3.12"'
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (!((major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22)) { console.error("Shop Buddy requires Node 20.19+ or Node 22.12+"); process.exit(1); }'

venv_python="$project_root/.venv/bin/python"
if [[ ! -x "$venv_python" ]]; then
    echo "Creating local Python environment..."
    python3 -m venv "$project_root/.venv"
fi

if [[ "$no_install" == false ]]; then
    echo "Installing/verifying Python packages..."
    "$venv_python" -m pip install --upgrade pip
    "$venv_python" -m pip install -r "$project_root/requirements.txt"

    echo "Installing/verifying React packages..."
    (cd "$project_root/frontend" && npm install)
fi

if [[ ! -f "$project_root/.env" ]]; then
    cp "$project_root/.env.example" "$project_root/.env"
fi
mkdir -p "$project_root/logs"

port_open() {
    "$venv_python" -c 'import socket, sys; sock = socket.socket(); sock.settimeout(0.3); result = sock.connect_ex(("127.0.0.1", int(sys.argv[1]))); sock.close(); raise SystemExit(0 if result == 0 else 1)' "$1"
}

if ! port_open 8000; then
    echo "Starting FastAPI backend..."
    nohup "$venv_python" -m uvicorn main:app --host 127.0.0.1 --port 8000 \
        >"$project_root/logs/api.log" 2>"$project_root/logs/api-error.log" &
    echo $! >"$project_root/logs/api.pid"
fi

if ! port_open 5173; then
    echo "Starting React frontend..."
    (
        cd "$project_root/frontend"
        nohup npm run dev -- --host 127.0.0.1 --port 5173 \
            >"$project_root/logs/frontend.log" 2>"$project_root/logs/frontend-error.log" &
        echo $! >"$project_root/logs/frontend.pid"
    )
fi

for _attempt in $(seq 1 60); do
    if port_open 8000 && port_open 5173; then
        break
    fi
    sleep 0.5
done

if ! port_open 8000; then
    echo "The API did not start. Check logs/api-error.log." >&2
    exit 1
fi
if ! port_open 5173; then
    echo "The React frontend did not start. Check logs/frontend-error.log." >&2
    exit 1
fi

"$venv_python" -c 'import json, urllib.request; response = json.load(urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5)); assert response.get("status") == "ok", response'

echo
echo "Shop Buddy is running."
echo "  Storefront: http://127.0.0.1:5173"
echo "  API docs:   http://127.0.0.1:8000/docs"
echo "  Logs:       $project_root/logs/"

