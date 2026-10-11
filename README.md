# Shop Buddy - UrbanNest Furnishings

Shop Buddy is a conversational shopping assistant with a FastAPI backend, a modern React interface, a SQLite product/cart store, and a stateful agent-style workflow. It supports product discovery, price and category filters, add/update/remove/view-cart actions, combined search-and-add requests, and follow-ups such as "add the second one".

## Runtime versions

- **Python:** 3.11 or 3.12; Python 3.12 is recommended and is the version used for the full local verification.
- **Node.js:** 20.19+ or 22.12+; Node 22 LTS is recommended. Node 24 is also supported.
- **npm:** the version bundled with the supported Node.js release.

Python 3.13+ is intentionally not selected yet because the agent framework dependency set is verified on Python 3.11/3.12. The frontend's Node constraint is also recorded in `frontend/package.json`, and `.nvmrc` selects Node 22.

## Quick start on Windows

Prerequisites: a supported Python and Node.js version from the table above must be installed and available in `PATH`.

1. Copy `.env.example` to `.env` and optionally add an AI key.
2. Run `start.cmd` (or `powershell -ExecutionPolicy Bypass -File .\start.ps1`).
3. Open `http://127.0.0.1:5173`. API docs are at `http://127.0.0.1:8000/docs`.

The first launch creates a local Python virtual environment and installs the backend and frontend packages. The app works without an AI key: its deterministic shopping tools and LangGraph memory still execute all operations. Provider order is OpenAI, then Gemini, then local response generation. Gemini is also attempted when OpenAI is configured but its gateway is unavailable. No request is sent to either provider when no key exists.

## Quick start on Linux

On Ubuntu 24.04 or Debian 12, install Python and the virtual-environment tools:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip curl
```

Install Node 22 with `nvm` (the version manager's official install method):

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.8/install.sh | bash
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
nvm install 22
nvm use 22
```

Then start both services from the project directory:

```bash
chmod +x start.sh
./start.sh
```

The first run installs dependencies. Later starts can skip that check with `./start.sh --no-install`. The storefront is available at `http://127.0.0.1:5173`, API documentation at `http://127.0.0.1:8000/docs`, and service logs under `logs/`.

The reference proxy belongs in `OPENAI_BASE_URL`. If you use an official OpenAI key instead of that proxy, leave `OPENAI_BASE_URL` empty so the SDK uses `https://api.openai.com/v1`. Gemini defaults to the current `gemini-3.5-flash` model; either model remains configurable in `.env`.

## Accounts and personalization

Use **Sign in** in the storefront to create a local account or return to one. Passwords are salted and PBKDF2-hashed; the browser receives an opaque 30-day access token while the server keeps only its hash. For a signed-in user, carts and conversation memory are stored under the account rather than the browser session.

The profile panel stores preferred categories, colors, room/project, and a per-piece budget. Searches and cart additions become weighted preference events, and the **More your kind of space** section ranks in-stock recommendations from those explicit and learned preferences. Anonymous visitors can still shop, but their cart and memory are browser-session scoped.

## API routes

- `GET /search_products/`
- `POST /add_product_to_cart/`
- `PUT /update_product_in_cart/`
- `DELETE /delete_product_from_cart/`
- `GET /get_cart_items/`
- `POST /chat`
- `GET /health`

The trailing-slash routes intentionally match the project brief. Every cart request accepts a `session_id`, so independent browser sessions stay separate.

## Workflow coverage

- **LangFlow:** `langflow/shop_buddy.flow.json` is the saved visual flow, and `langflow/components/shop_buddy/tools.py` contains five discoverable Tool Mode components. Run `start-langflow.cmd` when you need the visual editor at `http://127.0.0.1:7860`. It uses a separate environment because the full authoring server has a very large optional dependency set.
- **CrewAI:** `shop_buddy/crewai_runtime.py` defines the three specialized agents, three sequential tasks, and five real `@tool` FastAPI integrations. Set `WORKFLOW_MODE=crewai` to make `/chat` use it when an AI key is configured.
- **AutoGen:** `shop_buddy/autogen_runtime.py` defines the three `AssistantAgent`s, `UserProxyAgent`, registered functions, `GroupChat`, manager, disabled disk cache, and per-request reset. Set `WORKFLOW_MODE=autogen` to select it.
- **LangGraph:** the default production path uses a compiled `StateGraph`, conditional routing, a `MemorySaver`, real search/cart node execution, structured `ShopState`, and durable SQLite conversation memory. Set `WORKFLOW_MODE=langgraph` (the default).
- **Deployment readiness:** `docs/DEPLOYMENT.md`, environment templates, health checks, frontend build scripts, and Windows startup files are included. Secrets and SQLite data are excluded from Git.

React replaces Streamlit by explicit project decision. SQLite replaces Odoo for the self-contained free/local build; the exact REST contracts remain isolated so an Odoo adapter can be introduced later without changing the UI or agent tools.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd --prefix frontend run build
```

