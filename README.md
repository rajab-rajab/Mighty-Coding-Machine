# Mighty Coding Machine (MCM)

[![Python](https://img.shields.io/badge/Python-3.14%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Backend-Flask-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![OpenAI](https://img.shields.io/badge/AI-OpenAI-412991?logo=openai&logoColor=white)](https://platform.openai.com/)
[![PyWebView](https://img.shields.io/badge/Desktop-PyWebView-2F2F2F)](https://pywebview.flowrl.com/)

Mighty Coding Machine (MCM) is a Windows desktop coding agent for building, understanding, debugging, reviewing, and operating software projects from one IDE-style workspace. It combines a Flask + Flask-SocketIO backend with a native PyWebView shell, Monaco Editor, xterm-style terminal output, SQL tooling, persistent memory, and local semantic code search.

## Devpost Submission Guide

### What MCM Demonstrates

MCM turns an implementation request into a visible local-development workflow: it routes work to a focused specialist,
generates and reviews changes, saves them inside a workspace-confined project, opens the result in Monaco, and runs the
active file through an integrated Windows terminal. The same desktop workspace also supports semantic codebase search,
Git source control, SQL exploration, persistent session history, and opt-in MCP extensions.

### Reproducible Setup

1. Install Python 3.14 or newer and Git for Windows.
2. Create and activate the virtual environment, then install `backend/requirements.txt` as shown in [Quick Start](#quick-start).
3. Copy or edit `backend/.env` and set `OPENAI_API_KEY`. The `MODEL` value selects the OpenAI model used by live agent requests.
4. Run `python app.py`, or launch `dist-mcp/My MCM/My MCM.exe` from its complete distribution directory.
5. In chat, request a small Python project, review the generated change, and select **Run** to execute the active file.

### Sample Data

No external dataset is required. MCM creates projects in its workspace and indexes them locally. For a short database
demo, connect SQLite to a workspace file such as `sqlite:///demo.db`, then run these statements separately in the Database panel:

```sql
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0
);

INSERT INTO todos (title, done) VALUES ('Prepare MCM demo', 1);
SELECT * FROM todos;
```

### How GPT-5.6 and Codex Accelerated Development

GPT-5.6 and Codex were used as an engineering collaborator during development: they accelerated repository exploration,
startup and request-flow debugging, focused Python and JavaScript changes, test creation, security review, documentation,
and PyInstaller packaging verification. The final architecture and implementation decisions were reviewed and directed by
the project author, Rajab Baig. MCM itself uses the OpenAI API model configured through `MODEL`; model availability and
access are controlled by the user's OpenAI account.

### Key Technical Decisions

- **Windows reliability:** Flask-SocketIO uses standard threading rather than eventlet, and the Flask server starts in a daemon thread before PyWebView opens the native window.
- **Safe local operations:** Workspace-root validation, SQL confirmation, approval levels, and constrained tool execution protect local files and sensitive actions.
- **Local-first code intelligence:** ChromaDB default embeddings keep RAG and memory useful without requiring an OpenAI key for retrieval.
- **Conditional specialists:** Agents, skills, and tools are routed by request intent, avoiding expensive multi-agent chains for simple work.
- **Practical distribution:** PyInstaller uses `--onedir` so PyWebView, Flask, ChromaDB, and bundled assets start reliably on Windows.

## Architecture

```text
┌──────────────────────────────────────────────────────────────┐
│              MIGHTY CODING MACHINE (MCM) - Windows App      │
│                  (Wrapped in PyWebView)                      │
├────────────────────────┬─────────────────────────────────────┤
│  HTML + CSS + JS       │        PYTHON BACKEND               │
│  (Served by Flask)     │        Flask + Flask-SocketIO       │
│  + Alpine.js / HTMX    │        + OpenAI AgentSDK            │
│  + Monaco Editor (CDN) │        + GPT-5.6 / Codex           │
│  + xterm.js (CDN)      │                                     │
├────────────────────────┼─────────────────────────────────────┤
│  Frontend Panels       │  AgentSDK Orchestration (6 Agents)  │
│  - Chat UI              │  ┌─────────────────────────────┐    │
│  - Editor              │  │   Orchestrator              │    │
│  - DB Visualizer       │  │   Code  Database            │    │
│  - Terminal            │  │   Debug  Review             │    │
│  - Skills Panel        │  │   Project                   │    │
│  - RAG Search          │  └─────────────────────────────┘    │
│                        │  Tools + PyWebView File Bridge      │
├────────────────────────┴─────────────────────────────────────┤
│  Socket.IO (Real-time Streaming)                             │
│  ChromaDB (Memory) + SQLite (Metadata)                       │
└──────────────────────────────────────────────────────────────┘
```

## Features

- **Conditional specialist orchestration:** Orchestrator, Planner, Code, Database, Debug, Review, Project, Test, Frontend,
Git, Security, and Deployment agents with streamed handoffs. New specialists activate only for matching requests.
- **Quality workflow:** Complex requests receive an explicit plan and acceptance criteria; implementation work is verified by generated and executed tests before review.
- **Request observability:** Cancel or retry requests and inspect model, token usage, execution time, and agent trace telemetry.
- **Prompt caching:** Stable global templates, role instructions, and tool prefixes use deterministic OpenAI cache keys;
  cache-hit tokens are reported in the agent metrics panel. Disable with `CM_PROMPT_CACHE_ENABLED=false` when needed.
- **Structured handoffs:** Every request carries authoritative task state containing the objective, constraints, plan,
decisions, artifacts, completed work, next actions, risks, and handoff history into each specialist turn.
- **Explainable routing:** Handoffs record a bounded confidence score and the reason for selecting the next specialist;
the trace displays both values for transparent agent decisions.
- **Persistent agent analytics:** CM stores per-agent run outcomes in `workspace/agent_metrics.db`, including success
rates, failures, cancellations, execution time, token totals, and recent history.
- **Bounded agent execution:** Every agent has an explicit token budget and timeout; transient failures retry at most
two times, with retry activity reported to the UI before the request fails safely.
- **Selective quality gates:** Security is a release/risk gate, Deployment requires elevated approval, Git writes require
confirmation, Frontend handles UI-only work, and Test/Review remain conditional quality gates.
- **Safe change review:** Agent file writes pause for an explicit unified-diff Accept/Reject decision before being applied.
- **Local code intelligence:** ChromaDB uses its default local embedding model for offline codebase RAG and persistent memory.
- **Hybrid retrieval:** Codebase search combines ChromaDB semantic retrieval with workspace-confined exact text matching,
  improving results for both natural-language questions and precise symbols, filenames, and error messages.
- **Structured agent contracts:** Model-generated tool arguments are validated against their declared schemas before any
  tool runs; invalid payloads return safe tool errors instead of reaching execution code.
- **Offline regression checks:** Routing evaluations run without API calls to catch accidental specialist-selection
  regressions during development and packaging.
- **Secure credentials:** Windows builds can store the OpenAI key using user-bound DPAPI through the PyWebView bridge;
  plaintext `.env` remains a compatibility fallback. Configure `CM_SECURE_CREDENTIALS_ENABLED=false` to disable it.
- **Controlled indexing:** Manual reindexing, progress/error reporting, file-type filters, and incremental updates are available from the UI.
- **Professional editor:** Monaco Editor, SQL editor, diff presentation events, Quick Start welcome prompts, command palette, and resizable panels.
- **Integrated operations:** Workspace-confined file bridge, Windows terminal sessions, synchronous SQLAlchemy database tools, and Socket.IO streaming.
- **Source control:** Repository initialization, branch switching, commit history, staged/unstaged diff highlighting, stage/unstage, local commits, and configured remote push/pull scoped to the active workspace.
- **Skills and extension points:** Dynamic skill injection plus structured MCP and deployment package boundaries for future integrations.
- **Governed MCP integration:** Optional Fetch, Git, GitHub, Codex CLI bridge, and remote HTTP MCP presets are disabled by default; CM conditionally launches approved servers, discovers permitted tools, logs calls, applies timeouts, and exposes only safe connected tools to agents.
- **Built-in skill catalog:** Python, JavaScript, SQLite, Backend API, Frontend UI, Testing and Quality, Security Audit,
  Git Workflow, Windows Packaging, Documentation, Performance Diagnostics, and Codebase RAG. Skills are opt-in per
  request, so larger toolsets do not inflate normal prompts or add latency to unrelated work.
- **Read-only quality tools:** Selected quality-oriented skills can inspect project inventory, search exact workspace text,
  review dependency manifests, and parse Python syntax without installing packages, executing shell commands, or
  modifying files.
- **Windows-native delivery:** PyWebView desktop window, system tray lifecycle, secure user workspace, and PyInstaller `--onedir` packaging.

## Quick Start

From PowerShell in the repository root:

```powershell
cd coding-machine
..\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
python app.py
```

For a new environment, use Python 3.14 or newer:

```powershell
py -3.14 -m venv ..\.venv
..\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
```

Set `OPENAI_API_KEY` in `backend/.env` to enable live agent calls. Without a key, the application still starts and local RAG, memory, editor, terminal, and database features remain available.

Git must be installed and available on `PATH` for Source Control. Open the `⑂` activity icon to inspect changes, view diffs, stage or unstage files, and create local commits. Push and pull are intentionally not automated.

Open the `⌘` activity icon for **MCP Server Manager**. Select a preset, save its configuration, approve its launch, and connect to discover tools. The Fetch, Git, and GitHub presets require their own external runtime (`uvx` or `npx`); CM never installs or starts them automatically. See [backend/mcp/README.md](backend/mcp/README.md) for safe configuration details.

## Configuration

`backend/.env` supports:

```dotenv
OPENAI_API_KEY=your_key_here
MODEL=gpt-4o
WORKSPACE_ROOT=./workspace
```

Packaged builds use an explicitly configured `WORKSPACE_ROOT` when provided. Local repository builds prefer the repository `workspace/` directory; installed builds fall back to `%USERPROFILE%\CodingMachineWorkspace` so writable data stays out of read-only installation directories. ChromaDB data and preferences use the selected workspace root.

## Testing

Run the complete backend suite from `coding-machine/`:

```powershell
..\.venv\Scripts\python.exe -m pytest backend\tests\ -q
```

The suite covers path traversal, destructive SQL confirmation, workspace file operations, code execution, API routes, and standardized Flask errors. OpenAI calls are mocked or avoided so tests do not consume API credits.

Packaged-EXE smoke tests are opt-in because they start a native Windows GUI process. Close any running CM instance, then run:

```powershell
$env:CM_RUN_EXE_SMOKE = "1"
..\.venv\Scripts\python.exe -m pytest backend\tests\test_packaged_exe.py -q
```

Set `CM_EXE_PATH` when testing a build outside the default `dist-source-control-final`, `dist-ai-workflow`, or `dist` locations. The smoke tests use a temporary workspace, clear the OpenAI key, verify health and bundled assets, and check encoded traversal handling.

## Building the Windows App

CM intentionally uses PyInstaller **onedir** packaging. ChromaDB, ONNX assets, Flask, and PyWebView are not suitable for the startup and extraction behavior of one-file packaging.

```powershell
cd coding-machine
..\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
pyinstaller coding-machine.spec
```

The distributable output is:

```text
dist-mcp/My MCM/My MCM.exe
```

Launch `My MCM.exe` from the complete `dist-mcp/My MCM/` directory. The executable starts without a console window, opens the native MCM window, and creates a system tray item named **Mighty Coding Machine (MCM)**. Use **Quit Mighty Coding Machine** from the tray menu to exit.

## Security

- All workspace paths pass through `backend/security.py` and reject traversal and symlink escapes.
- SQLite file URLs are also confined to the configured workspace.
- Destructive SQL statements require explicit confirmation before execution.
- Agent Python execution uses AST preflight plus a subprocess audit hook; external system-file writes, deletes, renames, native escape modules, and process spawning are blocked.
- Agent Node execution rejects filesystem/process-control modules and runtime escape APIs; Test Agent pytest runs use the same mutation guard.
- Agent database operations block unverifiable or external file targets, extension loading, and operating-system program execution.
- Dangerous actions use three approval levels: automatic for safe reads and common local runs, confirmation for ordinary writes or publishing commands, and elevated typed `APPROVE` confirmation for destructive SQL, destructive shell commands, and deployment gates.
- Approval requests are client-owned, expire automatically, can be cancelled with the agent request, and are displayed in the desktop UI before execution.
- Every agent and selectable skill receives the shared engineering contract in `backend/skills/global_template.py`, covering intent preservation, inspect-plan-implement-test-review workflow, security, maintainability, and truthful reporting.
- Each agent also receives a dedicated role playbook from `backend/skills/agent_templates.py`, with specialized checklists for planning, coding, databases, debugging, review, scaffolding, testing, and orchestration.
- The PyWebView bridge exposes only workspace-scoped read, write, and tree operations.
- Agent and Flask failures are converted into visible error events or standardized JSON responses.

## Project Layout

```text
coding-machine/
├── app.py
├── coding-machine.spec
├── backend/
│   ├── agents/       # orchestration and six agent definitions
│   ├── memory/       # ChromaDB memory and SQLite preferences
│   ├── rag/          # chunking, indexing, search, and watcher
│   ├── security.py   # centralized path and SQL validation
│   ├── tests/        # pytest suite
│   └── tools/        # file, code, terminal, database, memory, and RAG tools
└── frontend/
    ├── index.html
    ├── css/styles.css
    └── js/
```

## License and Use

Coding Machine is a local development tool. Review generated code, SQL, shell commands, and deployment output before using them in production environments.
