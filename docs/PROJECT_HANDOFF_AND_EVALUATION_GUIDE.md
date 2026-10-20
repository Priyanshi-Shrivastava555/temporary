# Shop Buddy Project Handoff and Evaluation Guide

Status date: 20 October 2026

This is the working context for continuing development and evaluation of Shop Buddy, an AI-powered conversational shopping assistant for UrbanNest Furnishings. A new developer or AI assistant should read this file, `README.md`, the current source, and the latest diagnostic reports before changing startup or authentication behavior.

The application is substantially implemented and passes its repository tests and React production build. The immediate unresolved problem is external Phase 1 evaluation: the project-managed LangFlow service and local Phase 1 smoke test pass, but the VDI evaluator reports that `LANGFLOW_API_KEY` is not set or cannot authenticate. Evaluation attempts are limited, so do not request another evaluation until the VDI's existing service and evaluator environment have been captured and the authentication mismatch is explained.

## Instructions for the next developer or AI assistant

1. Treat the repository and the original five-phase brief as the sources of truth. Do not rebuild the project from scratch.
2. Preserve React as the frontend. The user explicitly rejected Streamlit even though the assessment brief mentions it.
3. Preserve SQLite as the self-contained database unless the evaluator proves that live Odoo integration is mandatory. Odoo variables remain in `.env` for compatibility.
4. Never commit or print API keys, passwords, or bearer tokens. Diagnostic files may contain only configured or missing status and one-way fingerprints.
5. Do not spend another external evaluation attempt merely because a local smoke test passes. First explain why the evaluator process will see the same service, flow, and `LANGFLOW_API_KEY`.
6. Before modifying or restarting a VDI-provided LangFlow service, run the read-only service inspector documented below and preserve its report.
7. Keep fixes compatible with both Linux and Windows. Phase-specific assessment startup is currently implemented primarily in `start.sh`; `start.ps1` and `start.cmd` start the ordinary React and FastAPI application.

## Original project objective

Shop Buddy must let a customer use natural language to:

- Search and filter furniture products.
- Receive grounded product recommendations.
- Add products to a cart.
- Update cart quantities.
- Remove cart items.
- View the current cart.
- Combine search and cart operations in one request.
- Refer to earlier results with phrases such as “the second one” and “increase its quantity.”
- Use a different orchestration framework in each assessment phase.

The original project has five sequential phases with a minimum target score of 80 out of 100 per phase and a limited number of attempts. The technologies named by the brief are LangFlow, CrewAI, AutoGen, LangGraph, FastAPI, OpenAI through the assessment proxy, Odoo, a frontend, Git, and AWS EC2.

## Deliberate implementation decisions

| Brief or concern | Current decision |
|---|---|
| Streamlit frontend | Replaced with React at the user's explicit request. |
| Odoo backend | Replaced with SQLite for the free, self-contained build. The five required REST contracts are preserved, and Odoo variables remain configurable. |
| OpenAI only | Provider selection tries OpenAI first and Gemini second when `SHOP_BUDDY_AI_PROVIDER=auto`. Deterministic operations remain functional with neither key. |
| LangFlow dependencies | Installed in isolated `.langflow-venv` because LangFlow has a large and conflicting dependency tree. Runtime is pinned to LangFlow and lfx 1.12.5. |
| General application environment | Installed in `.venv` with FastAPI, LangGraph, CrewAI, AutoGen, OpenAI, and Gemini packages. |
| Phase evaluation on a disk-limited VDI | `--api-only` skips Node packages and the React service for Phase 1 and Phase 2. It does not skip FastAPI, agent frameworks, LangFlow for Phase 1, registration, diagnostics, or smoke tests. |
| Flow name | The registered evaluator-facing name is exactly `Shop_Buddy`; its stable execution endpoint is `shop-buddy`. The human requirement called it “Shop Buddy,” but prior evaluator alignment work established the underscore form. |

## Current architecture

```text
React on 127.0.0.1:5173
        |
        v
FastAPI on 127.0.0.1:8000
        |
        +-- five shopping REST tools
        +-- authentication and preferences
        +-- SQLite catalogue, carts, users, and durable memory
        |
        +-- Phase 2: CrewAI runtime
        +-- Phase 3: AutoGen runtime
        +-- Phase 4 and normal mode: LangGraph runtime

Phase 1 additionally runs LangFlow on 127.0.0.1:7860
        |
        +-- Shop_Buddy visual flow
        +-- orchestration, search, and cart agents
        +-- five custom FastAPI tools
```

The FastAPI workflow mode is selected at launch without rewriting `.env`:

| Phase | FastAPI workflow | Additional service |
|---|---|---|
| Phase 1 | `langgraph` | LangFlow 1.12.5 on port 7860 |
| Phase 2 | `crewai` | None |
| Phase 3 | `autogen` | None |
| Phase 4 | `langgraph` | None |
| Phase 5 | `langgraph` | React production build check |

## Repository map

| Path | Purpose |
|---|---|
| `main.py` | ASGI entry point exposing `shop_buddy.api:app`. |
| `shop_buddy/api.py` | FastAPI routes, health metadata, authentication, preferences, catalogue, cart, and chat. |
| `shop_buddy/store.py` | SQLite schema, seeded products, carts, users, token sessions, preferences, recommendation events, and durable conversation state. |
| `shop_buddy/workflow.py` | Intent classification, deterministic tool execution, provider response writing, framework selection, fallback behavior, and contextual product resolution. |
| `shop_buddy/langgraph_runtime.py` | `ShopState`, `StateGraph`, conditional routing, search and cart nodes, response node, and `MemorySaver`. |
| `shop_buddy/crewai_runtime.py` | Three CrewAI agents, three tasks, and five `@tool` integrations. |
| `shop_buddy/autogen_runtime.py` | Three assistant agents, one `UserProxyAgent`, registered functions, `GroupChat`, manager, cache disabled, and per-request reset. |
| `shop_buddy/llm.py` | Optional OpenAI then Gemini response writer with deterministic fallback. |
| `frontend/` | React and Vite storefront, chat, cart drawer, authentication, profile preferences, and recommendations. |
| `langflow/shop_buddy.flow.json` | Exported `Shop_Buddy` visual workflow. |
| `langflow/components/shop_buddy/` | LangFlow model and five custom tool components. |
| `start.sh` | Linux phase launcher, dependency installation, service lifecycle, LangFlow registration, diagnostics, and smoke tests. |
| `start.cmd`, `start.ps1` | Windows launcher for the ordinary React and FastAPI application. |
| `scripts/phase_smoke_test.py` | Evaluation-oriented smoke tests for all five phase profiles. |
| `scripts/register_langflow_flow.py` | Reconciles the saved flow with the server, archives conflicting legacy copies, and verifies the executable graph. |
| `scripts/ensure_langflow_api_key.py` | Creates, verifies, and securely persists a LangFlow service API key. |
| `scripts/phase1_diagnostics.py` | Writes the redacted Phase 1 readiness report. |
| `scripts/capture_vdi_environment.py` | Captures evaluator and environment evidence without exposing secrets. |
| `scripts/inspect_existing_ai_services.py` | Read-only inventory of existing AI services, ports, Python environments, authentication, routes, components, and flows. |
| `tests/` | Unit and integration coverage for endpoints, workflows, memory, providers, LangFlow registration, key handling, personalization, and diagnostics. |

## Runtime and environment requirements

- Python 3.11 or 3.12. Python 3.12 is recommended and was used on the VDI report.
- Node.js 20.19 or later in the Node 20 line, or Node.js 22.12 or later. Node 22 LTS is recommended. Node 20.19.3 is supported.
- npm supplied with Node.
- Linux utilities used by `start.sh`: `setsid`, `ps`, and a working `/proc` filesystem.
- FastAPI dependencies from `requirements.txt`.
- LangFlow 1.12.5 and lfx 1.12.5 from `requirements-langflow.txt` for Phase 1 only.

The important environment variables are:

| Variable | Purpose |
|---|---|
| `SHOP_BUDDY_AI_PROVIDER` | `auto`, `openai`, or `gemini`; `auto` tries OpenAI and then Gemini. |
| `OPENAI_API_KEY` | OpenAI or assessment gateway credential. |
| `OPENAI_BASE_URL` | Assessment proxy by default: `https://llmgateway-cognizant-assessment.tekstac.com/v1`. Use `https://api.openai.com/v1` or leave empty as appropriate for an official OpenAI key. |
| `OPENAI_MODEL` | Defaults to `gpt-4o-mini`. Must be accepted by the configured endpoint. |
| `GEMINI_API_KEY` | Gemini fallback credential. |
| `GEMINI_MODEL` | Configurable Gemini model, currently defaulted to `gemini-3.5-flash`. Confirm model availability when testing because model names change over time. |
| `SHOP_BUDDY_API_URL` | Internal shopping API base URL, normally `http://127.0.0.1:8000`. |
| `SHOP_BUDDY_DB_PATH` | SQLite path, normally `data/shop_buddy.db`. |
| `WORKFLOW_MODE` | Default framework outside phase launcher. `SHOP_BUDDY_WORKFLOW_OVERRIDE` takes precedence during phase startup. |
| `LANGFLOW_API_KEY` | Authenticates clients, including the evaluator, to LangFlow. It is not an OpenAI key. |
| `ODOO_ENDPOINT`, `ODOO_DB_NAME`, `ODOO_ADMIN_USERNAME`, `ODOO_ADMIN_PASSWORD` | Required by the original Phase 1 brief but currently reserved for a future Odoo adapter. SQLite is used when these values are incomplete. |

`.env` is ignored by Git. Never add it to a commit. The launcher loads it with override behavior and performs a small provider request to determine whether OpenAI or Gemini is actually usable. Provider errors are redacted and include the endpoint status so a wrong proxy credential can be distinguished from an OpenAI credential.

## Service URLs and startup commands

| Service | URL |
|---|---|
| React storefront | `http://127.0.0.1:5173` |
| FastAPI health | `http://127.0.0.1:8000/health` |
| FastAPI Swagger | `http://127.0.0.1:8000/docs` |
| FastAPI OpenAPI | `http://127.0.0.1:8000/openapi.json` |
| LangFlow UI and API | `http://127.0.0.1:7860` |

Linux phase commands:

```bash
./start.sh --phase1
./start.sh --phase2
./start.sh --phase3
./start.sh --phase4
./start.sh --phase5
./start.sh --stop
```

Use `--no-install` only after both required environments are complete. The first Phase 1 run must install `.venv` and `.langflow-venv`. For low disk space during API-focused Phase 1 or Phase 2 evaluation:

```bash
./start.sh --phase1 --api-only
./start.sh --phase2 --api-only
```

The services are detached with `nohup` and `setsid`, so no terminal stays open. PID files and logs are under `logs/`. `./start.sh --stop` stops only processes tracked as belonging to the project. An explicit phase run also checks stale listeners before starting fresh processes.

Windows ordinary application commands:

```powershell
start.cmd
# or
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

The Windows launcher starts React and FastAPI. It does not currently reproduce all Linux phase-selection and automated LangFlow evaluation behavior.

## FastAPI contracts

The five required tool routes intentionally include trailing slashes:

| Operation | Method and path | Inputs |
|---|---|---|
| Search | `GET /search_products/` | `query`, optional `max_price`, optional `category`, optional `limit` |
| Retrieve cart | `GET /get_cart_items/` | `session_id` query parameter |
| Add product | `POST /add_product_to_cart/` | `product_id` or `product_name`, `quantity`, `session_id` |
| Update product | `PUT /update_product_in_cart/` | `cart_item_id`, `product_id`, or `product_name`; plus `quantity` and `session_id` |
| Delete product | `DELETE /delete_product_from_cart/` | `cart_item_id`, `product_id`, or `product_name`; plus `session_id` |

Additional routes are:

- `POST /chat` with `message` and `session_id`.
- `POST /cart` for direct `add`, `update`, `delete`, and `view` operations.
- `GET /api/products` for the catalogue.
- `GET /health` for workflow and installed-framework status.
- `POST /auth/register`, `POST /auth/login`, `GET /auth/me`, and `POST /auth/logout`.
- `GET /preferences`, `PUT /preferences`, and `GET /recommendations` for signed-in users.

Anonymous carts and memory use the supplied browser `session_id`. Signed-in users use an account-bound session so their cart, memory, and preferences survive browser sessions. Passwords are PBKDF2-hashed with salts. The browser receives an opaque access token, and only its hash is stored.

## Implemented shopping and personalization behavior

- Search understands product phrases, price limits, and broad categories.
- Combined requests search and add in one turn.
- Follow-ups resolve ordinal references such as “add the second one.”
- Follow-ups can update the selected item with “increase its quantity to 3.”
- Durable SQLite memory survives a new workflow object or backend restart.
- The frontend keeps chat scrolling inside the chat panel; sending a message should no longer jump the page to the “Pieces with presence” section.
- Registration and login bind the cart and memory to the user account.
- Users can save favorite categories, favorite colors, room or project, and a per-item budget.
- Search and cart actions record weighted preference events.
- The personalized “More your kind of space” section ranks in-stock products from explicit and learned preferences.
- Without an AI key, deterministic shopping operations still work. With a validated key, the selected framework performs live execution or an LLM writes a grounded final response.

## Phase 1 LangFlow success criteria

### Required behavior

- FastAPI runs on port 8000 and exposes all five tool routes.
- LangFlow runs on port 7860.
- A saved visual flow contains Chat Input, Orchestration Agent, Product Search Agent, Cart Management Agent, Chat Output, and five API tools.
- Search is connected to the product agent; four cart tools are connected to the cart agent.
- Agent prompts clearly define intent routing, product discovery, and cart responsibilities.
- The flow is exported to the repository.
- The evaluator can authenticate to LangFlow and execute the flow.

### Current implementation

- Export: `langflow/shop_buddy.flow.json`.
- Registered name: `Shop_Buddy`.
- Endpoint: `shop-buddy`.
- Graph size: 11 nodes and 12 edges.
- Node IDs include one chat input, one model, three agents, one chat output, and five custom tools.
- The common model is connected to all three agents.
- Custom components communicate with the required FastAPI endpoints and return structured results.
- Registration detects executable changes in templates, prompts, outputs, and handles. It archives legacy duplicates and creates a fresh endpoint owner when needed.
- LangFlow and lfx are pinned to 1.12.5 in `.langflow-venv`.
- `ensure_langflow_api_key.py` uses LangFlow auto-login, creates a server-issued key named `Shop Buddy Evaluator`, verifies it against `/api/v1/flows/`, and atomically saves it to `.env` with the existing file mode.
- After verification, `start.sh` imports only `LANGFLOW_API_KEY` into the current user-systemd environment. This lets an evaluator launched by that manager use the same server-issued key; it is session-scoped and does not prove an already-running browser process has refreshed its environment.
- The live run payload is sent directly to `/api/v1/run/shop-buddy` with root fields `input_value`, `input_type`, `output_type`, and `session_id`. It is not incorrectly nested under `input_request`.

### Phase 1 smoke scenarios

1. `Show me office chairs.`
2. `Find an office chair under $500 and add it to my cart.`
3. `Add 2 conference chairs to my cart.`
4. `Change quantity to 3.`
5. `Show my cart.`
6. `Remove the conference chairs from my cart.`

The smoke test checks search results, combined intent, exact quantities, `GetCartItems` use, and successful deletion. It also verifies exactly one `Shop_Buddy` flow and one `shop-buddy` endpoint owner, 11 nodes, 12 edges, and three model connections. When a provider is validated, it performs a live LangFlow run and requires a JSON response containing an `outputs` list.

### Phase 1 definition of success

- `./start.sh --phase1` exits successfully.
- `phase1_diagnostics.txt` ends with `readiness=PASS` and `phase1_smoke=PASS`.
- Authenticated `GET http://127.0.0.1:7860/api/v1/flows/` returns HTTP 200 using the same key the evaluator process will receive.
- Exactly one canonical flow has `name=Shop_Buddy` and `endpoint_name=shop-buddy`.
- `POST /api/v1/run/shop-buddy` succeeds with a valid provider key.
- The external evaluation prerequisite recognizes LangFlow authentication and proceeds to test the pipeline.
- The external score reaches at least 80 out of 100.

### Current Phase 1 blocker

Local VDI evidence already showed:

- Linux with Python 3.12.3.
- LangFlow 1.12.5 and lfx 1.12.5.
- Project-owned LangFlow processes on port 7860.
- `LANGFLOW_API_KEY` configured and persisted; reported fingerprint `c8c50c956c88`.
- LangFlow health HTTP 200.
- Authenticated flow lookup HTTP 200.
- One `Shop_Buddy` flow and one `shop-buddy` endpoint owner.
- 11 nodes and 12 edges.
- OpenAPI run routes present.
- Local readiness passed.

Despite this, the external evaluator still returns 0 out of 100 at its prerequisite check with: `LangFlow authentication failed. Please set LANGFLOW_API_KEY environment variable.`

This means local server authentication is proven, but evaluator authentication is not. The likely possibilities are an evaluator process that does not load the project's `.env`, a stale or different key injected into the evaluator, or an expectation that the VDI-provided `/Software/langenv` service remain in use. These are hypotheses, not confirmed causes.

`start.sh --phase1` currently allows termination of an external process whose command contains `langflow run` on port 7860, then starts the project-pinned service. This was introduced to remove stale conflicting servers, but it may conflict with an evaluator that expects its preinstalled service. Do not change this again until the existing-service report is captured.

## Phase 2 CrewAI success criteria

### Required behavior

- Three specialized agents: orchestrator, product search, and cart management.
- Three tasks in orchestration, search, and cart order.
- Five backend tools using CrewAI's `@tool` decorator.
- Search agent owns one search tool; cart agent owns retrieve, create, update, and delete tools.
- `/chat` runs with `WORKFLOW_MODE=crewai`.
- Live provider execution uses the configured OpenAI proxy or Gemini fallback on Linux as well as Windows.

### Current implementation

- `shop_buddy/crewai_runtime.py` creates all three agents, all three tasks, and a sequential `Crew`.
- Tool functions are named `search_tool`, `retrieve_tool`, `create_tool`, `update_tool`, and `delete_tool`.
- Tools send real HTTP requests to FastAPI and return structured JSON.
- `XDG_DATA_HOME` and `CREWAI_STORAGE_DIR` keep CrewAI runtime storage inside the project on Linux.
- The health endpoint reports `workflow=crewai` and installed framework status.
- React is used instead of the brief's Streamlit requirement by explicit user decision.

### Phase 2 smoke scenarios

1. `Show me affordable chairs.`
2. `Find a desk under 5000.`
3. `Add 2 office chairs to my cart.`
4. `Update office chairs quantity to 3.`
5. `Delete desk pad from my cart.`

The smoke test verifies the three-agent structure, three tasks, five assigned tools, search results, price filtering, quantity 3, and deletion. If an AI provider passed startup validation, every response must include a completed `CrewAI Multi-Agent Runtime` trace rather than a deterministic fallback trace.

### Phase 2 definition of success

- `./start.sh --phase2`, or `./start.sh --phase2 --api-only` on a disk-limited API evaluator, exits successfully.
- `/health` returns `status=ok` and `workflow=crewai`.
- Framework structure validation passes.
- All five reference requests return correct state changes.
- With a valid key, the live CrewAI runtime completes instead of falling back.
- The external score reaches at least 80 out of 100.

## Phase 3 AutoGen success criteria

### Required behavior

- Orchestrator, product search, and cart `AssistantAgent` instances.
- A `UserProxyAgent` executes registered backend functions.
- Five structured backend tools are registered with appropriate caller and executor relationships.
- A four-agent `GroupChat` and `GroupChatManager` coordinate execution.
- Disk caching is disabled with `cache_seed=None`.
- Group chat messages and every agent are reset before an independent request.
- `/chat` runs with `WORKFLOW_MODE=autogen`.

### Current implementation

- `shop_buddy/autogen_runtime.py` implements all four agents, tool registration, group chat, manager, and reset logic.
- `cache_seed` is set to `None` in the LLM configuration.
- `reset()` clears `groupchat.messages` and resets each agent before `initiate_chat`.
- Tools call the same five FastAPI contracts and return structured results.
- React replaces Streamlit by user decision.

### Phase 3 smoke scenarios

1. `Show me affordable chairs.`
2. `Find a desk under 5000.`
3. `Add 2 conference chairs to my cart.`
4. `Update conference chairs quantity to 3.`
5. `Delete desk pad from my cart.`

The smoke test verifies four group-chat participants, disabled cache, reset behavior, functional searches and cart operations, and a completed `AutoGen Multi-Agent Runtime` trace when a provider is active.

### Phase 3 definition of success

- `./start.sh --phase3` exits successfully.
- `/health` returns `status=ok` and `workflow=autogen`.
- Structure and reset checks pass.
- All five reference requests produce correct results.
- With a valid provider, live AutoGen completes without fallback.
- The external score reaches at least 80 out of 100.

## Phase 4 LangGraph success criteria

### Required behavior

- A shared `ShopState` stores messages, intent, search results, cart state, tool results, and workflow progress.
- An orchestrator node conditionally routes to search, cart, or both.
- Search and cart nodes execute real operations.
- A compiled `StateGraph` uses a memory checkpointer.
- Multi-turn references work across requests.
- `/chat` runs with `WORKFLOW_MODE=langgraph`.

### Current implementation

- `shop_buddy/langgraph_runtime.py` defines `ShopState` and compiles orchestrator, product search, cart management, and response nodes.
- Conditional edges support search-only, cart-only, and search-then-cart execution.
- `MemorySaver` preserves active thread state.
- SQLite conversation records preserve durable state across workflow instances and backend restarts.
- State is isolated by anonymous session or signed-in account.

### Phase 4 smoke scenarios

The five Phase 2-style scenarios run with conference chairs, followed by this required multi-turn sequence in one session:

1. `Show me office chairs under $500.`
2. `Add the second one to my cart.`
3. `Increase its quantity to 3.`

The final cart must contain the resolved second product, Cedar Executive Chair, at quantity 3.

### Phase 4 definition of success

- `./start.sh --phase4` exits successfully.
- `/health` returns `status=ok` and `workflow=langgraph`.
- Search-only, cart-only, and combined routes execute correctly.
- Multi-turn selection and pronoun resolution work in the same session.
- Memory survives a new workflow instance.
- The external score reaches at least 80 out of 100.

## Phase 5 deployment success criteria

### Original requirement

The brief expects deployment to an Ubuntu 24.04 EC2 instance in the Mumbai region, FastAPI on port 8000, a public frontend on port 80, secure `.env` handling, service monitoring, and end-to-end shopping verification. The original brief says Streamlit, but this project intentionally uses React.

### Current implementation status

- Deployment preparation exists in `docs/DEPLOYMENT.md`.
- `./start.sh --phase5` builds the React production bundle and runs health and shopping smoke tests.
- FastAPI can run behind Nginx on `127.0.0.1:8000`.
- `frontend/dist` can be served by Nginx or another static server.
- `.env`, SQLite data, build output, virtual environments, logs, and runtime state are excluded from Git.
- Actual AWS provisioning, public DNS or IP setup, Nginx configuration, systemd units, TLS, and deployment have not been performed in this repository because the user initially allowed deployment to be deferred.

### Phase 5 definition of success

- `./start.sh --phase5` completes the React production build and end-to-end local smoke test.
- `GET /health` succeeds in the deployment environment.
- Nginx or an equivalent server exposes the React build publicly and proxies API traffic to FastAPI.
- FastAPI runs under a supervised non-root service such as systemd.
- `.env` exists only on the server with restrictive permissions.
- All six Phase 1 shopping scenarios work through the deployed frontend.
- Public accessibility and service restart behavior are verified on the EC2 instance.
- The external score reaches at least 80 out of 100.

Phase 5 is deployment-ready, not deployed. Do not claim completion of the cloud deliverable until an EC2 instance has been configured and verified.

## Automated validation and current evidence

On 20 October 2026, the current source passed:

```text
pytest: 30 passed
React production build: passed with Vite 8.3.4
```

The test suite covers:

- All five required API tool endpoints.
- Health metadata and launcher workflow override.
- OpenAI-to-Gemini fallback and actionable proxy authentication errors.
- Core search, add, update, delete, combined, and no-key scenarios.
- Durable memory and pronoun or ordinal follow-ups.
- Account-bound carts, preferences, and personalization.
- LangFlow key persistence without secret exposure.
- LangFlow flow signatures, duplicate selection, update compatibility, exported name, and external model mode.
- Linux listener-to-process mapping.
- Existing-service report redaction and capability summarization.

Repository tests do not prove that the external evaluator inherits environment variables or authenticates to the intended LangFlow instance. That is the remaining Phase 1 problem.

## Diagnostic collection before another Phase 1 attempt

Run these commands on the VDI before `start.sh`, before stopping port 7860, and before clicking Evaluate:

```bash
git pull origin main

./.venv/bin/python scripts/capture_vdi_environment.py \
  --env-file .env \
  --output vdi_environment_diagnostics.txt

./.venv/bin/python scripts/inspect_existing_ai_services.py \
  --env-file .env \
  --output existing_ai_services_report.txt
```

The second collector is read-only. It records:

- AI-related process IDs, parent IDs, executables, working directories, and listening ports.
- Project, process, and service configuration without exposing secrets.
- Relevant package versions in `.venv`, `.langflow-venv`, `/Software/langenv`, and running Python interpreters.
- LangFlow health, OpenAPI paths, flow list, authentication behavior for discovered key fingerprints, component catalogue, and supported capability groups.
- FastAPI health and OpenAPI routes.
- Whether the port 7860 listener appears project-managed or VDI-preinstalled and whether it is technically reusable.

Commit only the redacted reports:

```bash
git add vdi_environment_diagnostics.txt existing_ai_services_report.txt
git commit -m "capture existing VDI AI services"
git push origin main
```

Then inspect those reports before changing `start.sh` or asking the user to evaluate. Do not include `.env` or any log containing a raw credential.

## Phase 1 troubleshooting decision guide

Use the report evidence in this order:

1. If no process owns port 7860, determine whether the evaluator expects the project to start LangFlow or whether a VDI service failed before the project ran.
2. If `/Software/langenv/bin/python3` owns port 7860, inspect its LangFlow version, authentication mode, existing flows, and key fingerprint. Prefer updating or registering the flow into that service if it is evaluator-owned and compatible.
3. If `.langflow-venv/bin/python` owns port 7860, confirm its process environment and `.env` contain the same `LANGFLOW_API_KEY` fingerprint.
4. Test `/api/v1/flows/` with no key and with each discovered key. HTTP 200 identifies a usable credential; HTTP 401 or 403 identifies a mismatch.
5. Confirm that the evaluator can load `.env` or inherits the user-systemd environment. The Phase 1 launcher imports its verified key into the latter, but a key persisted in the repository directory does not automatically enter an already-running evaluator process.
6. Confirm exactly one `Shop_Buddy` flow owns `shop-buddy` and that `/api/v1/run/{flow_id_or_name}` exists.
7. Only after the evaluator's credential source is understood should startup either reuse the VDI service or replace it with the project service.
8. Run the project smoke test one final time, inspect redacted reports and `logs/langflow-error.log`, and only then use an evaluation attempt.

## Important fixes already made

- Corrected the frontend chat scroll so a sent message does not scroll the whole page to “Pieces with presence.”
- Added registration, login, logout, bearer sessions, account-bound carts, saved preferences, learned preference events, and personalized recommendations.
- Added durable SQLite conversation memory in addition to LangGraph's in-process checkpointer.
- Added OpenAI startup validation and Gemini fallback.
- Added phase-specific Linux startup, API-only mode, stop behavior, detached logs, version checks, and smoke tests.
- Added real CrewAI and AutoGen framework structure checks, including Linux storage settings.
- Fixed the LangFlow run request shape for LangFlow 1.12.
- Fixed stale flow reconciliation so changed component code and prompts replace the executable graph rather than leaving an old compiled endpoint.
- Added PATCH-to-PUT compatibility for flow updates.
- Added stale listener recovery and guarded process termination.
- Added server-generated LangFlow service keys, verification, atomic `.env` persistence, and redacted diagnostics.
- Added failure output that names the exact phase check, HTTP status, response detail, traceback, and recent service log lines.
- Added read-only VDI environment and existing AI service collectors.

## Known gaps and risks

- The external Phase 1 evaluator authentication failure remains unresolved even though local Phase 1 readiness passes.
- Replacing the VDI-preinstalled LangFlow service may be wrong if the evaluator is bound to that service or its credential. The new collector exists to settle this question.
- The Odoo variables are present, but there is no live Odoo adapter. SQLite is the active data source.
- React intentionally differs from the brief's Streamlit wording. If an evaluator checks for a literal `app.py` or Streamlit process instead of functional frontend behavior, it may need assessment-specific compatibility work without replacing React.
- Phase 5 has not been deployed to AWS.
- The active remote is currently GitHub `origin/main`, while the original brief names GitLab. Confirm the submission platform before final submission.
- AI model and proxy availability are external. A configured key is not sufficient; the selected endpoint must accept the configured model.
- `--no-install` is valid only when all needed packages already exist. The launcher deliberately fails early when an environment is incomplete.

## Completion checklist for any phase

- The correct phase command performs a clean, successful startup.
- `/health` reports `status=ok`, the expected workflow mode, and required frameworks installed.
- Every required REST endpoint is reachable at the exact documented path and method.
- The phase smoke test passes with disposable session data and cleans up afterward.
- If an AI key is configured, the real phase runtime completes rather than silently falling back.
- Logs contain no unhandled traceback, secret, or opaque error without context.
- The evaluator-facing process uses the same ports, environment, credentials, and flow names as the project smoke test.
- Required exported workflow or deployment artifacts are present and committed.
- The external evaluation reaches at least 80 out of 100.

## Safe commands for ongoing verification

```bash
# Repository tests
./.venv/bin/python -m pytest -q

# A specific phase after dependencies are installed
./start.sh --phase1 --no-install

# Stop detached project services
./start.sh --stop

# Inspect service logs
tail -n 100 logs/api-error.log
tail -n 100 logs/langflow-error.log

# Confirm service endpoints
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/openapi.json
curl -fsS http://127.0.0.1:7860/health_check
```

On Windows:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd --prefix frontend run build
```

The next action is evidence collection on the untouched VDI service, not another evaluation attempt.
