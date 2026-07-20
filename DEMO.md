# Mighty Coding Machine (MCM) Competition Demo

This script is designed for a five-to-eight-minute judge demonstration.

## 1. Setup and Native Shell

1. Start `dist-mcp/My MCM/My MCM.exe` or run `python app.py` from `coding-machine/`.
2. Point out that the app opens as a native Windows window rather than a browser tab.
3. Show the **Mighty Coding Machine (MCM)** system tray icon and its **Quit Mighty Coding Machine** command.
4. Show the dark IDE layout, resizable sidebar, terminal panel, agent chat, and indexing status.

## 2. Code Generation and Diff Review

1. In the MCM Agent chat, enter: **Write a Flask API for todos**.
2. Point out the Orchestrator handoff to the Planner Agent, the implementation specialist, and the Test Agent in the trace chips.
3. Show the Planner Agent's visible steps and acceptance criteria, then show the Test Agent creating and running focused tests.
4. Show the streamed response and the presented code/diff event.
5. Review the proposed changes before accepting them. Demonstrate rejecting a change when it is not desired.
6. Use `Ctrl+S` to save the active file.

## 3. Integrated Terminal

1. Press `Ctrl+F5` or click **Run**.
2. Show the generated `main.py` running in the integrated terminal panel.
3. Enter a follow-up command directly in the terminal to demonstrate live stdout/stderr streaming.
4. Drag the terminal resizer to show that the panel height is adjustable.

## 4. Database Visualizer

1. Open the **Database** tab in the right panel.
2. Connect SQLite using a workspace-relative file such as `todos.db`.
3. Ask CM: **Create a SQLite DB for these todos**.
4. Show the schema browser listing tables.
5. Run a query in the SQL editor and show the returned data grid.
6. Demonstrate that a destructive query pauses and asks for confirmation instead of executing silently.

## 5. Codebase RAG

1. Wait for the bottom status bar to report that indexing is complete.
2. Press `Ctrl+Shift+F` and search for `Todo model`.
3. Open a result to load its file in Monaco.
4. Ask CM: **How did I implement the Todo model?**
5. Show the agent using `codebase_search` and explain that the default ChromaDB embedding model runs locally without an OpenAI key.

## 6. MCP Integration

1. Open the **MCP** tab using the `⌘` activity icon.
2. Select **Mighty Coding Machine MCP Server (Codex CLI bridge)**, click **Save**, then click **Connect**.
3. Approve the launch request and show the discovered read-only tools: `workspace_info`, `workspace_list_files`, `workspace_read_file`, and `codebase_search`.
4. Select `workspace_info`, call it with `{}`, and show the workspace-scoped result and audit log behavior.
5. Point out that write tools remain blocked by the read-only policy, while external Fetch/Git/GitHub servers stay disabled until explicitly configured.

## 7. Deploy and Export

1. Ask CM: **Export the project as a ZIP**.
2. Show the Project Agent handoff and the generated deployment/export response.
3. Explain that the backend provides structured deployment and MCP extension points for adding provider-specific exporters.

## 8. Close

1. Open the command palette with `Ctrl+Shift+P`.
2. Demonstrate **Toggle Terminal** and **Open File**.
3. Close the application from the system tray menu to demonstrate the Windows lifecycle integration.
