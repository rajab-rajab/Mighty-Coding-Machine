(function () {
  const THEME_PREFERENCE_KEY = "theme";
  const RIGHT_PANEL_ZOOM_PREFERENCE_KEY = "right-panel-zoom";
  const VALID_THEMES = new Set(["colorful", "dark"]);
  const PANEL_ZOOM_MIN = 100;
  const PANEL_ZOOM_MAX = 140;

  function normalizeTheme(theme) {
    return VALID_THEMES.has(theme) ? theme : "colorful";
  }

  function readCachedTheme() {
    try {
      return normalizeTheme(window.localStorage.getItem(`cm-preference:${THEME_PREFERENCE_KEY}`));
    } catch (error) {
      return "colorful";
    }
  }

  function readCachedPanelZoom(key) {
    try {
      const value = Number(window.localStorage.getItem(`cm-preference:${key}`));
      return Number.isFinite(value) ? Math.max(PANEL_ZOOM_MIN, Math.min(PANEL_ZOOM_MAX, value)) : PANEL_ZOOM_MIN;
    } catch (error) {
      return PANEL_ZOOM_MIN;
    }
  }

  function cachePanelZoom(key, value) {
    try {
      window.localStorage.setItem(`cm-preference:${key}`, String(value));
    } catch (error) {
      console.warn("Panel zoom cache is unavailable", error);
    }
  }

  function applyTheme(theme) {
    const normalizedTheme = normalizeTheme(theme);
    document.documentElement.dataset.theme = normalizedTheme;
    const themeColor = document.querySelector('meta[name="theme-color"]');
    if (themeColor) {
      themeColor.setAttribute("content", normalizedTheme === "dark" ? "#0d1117" : "#f4f8ff");
    }
    try {
      window.localStorage.setItem(`cm-preference:${THEME_PREFERENCE_KEY}`, normalizedTheme);
    } catch (error) {
      console.warn("Theme cache is unavailable", error);
    }
    return normalizedTheme;
  }

  applyTheme(readCachedTheme());

  function formatMessage(payload) {
    if (typeof payload === "string") {
      return payload;
    }

    if (payload && typeof payload.message === "string") {
      return payload.message;
    }

    return JSON.stringify(payload);
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function createSessionId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return `session-${window.crypto.randomUUID()}`;
    }
    return `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function normalizeWorkspaceRelativePath(filePath) {
    let normalized = String(filePath || "").replaceAll("\\", "/").replace(/^\.\/+/, "");
    const workspaceRoot = window.cmAppInstance && window.cmAppInstance.sessionContext
      ? window.cmAppInstance.sessionContext.workspaceRoot
      : "";
    const normalizedRoot = String(workspaceRoot || "").replaceAll("\\", "/").replace(/\/$/, "");
    const lowerPath = normalized.toLowerCase();
    const lowerRoot = normalizedRoot.toLowerCase();
    if (lowerRoot && (lowerPath === lowerRoot || lowerPath.startsWith(`${lowerRoot}/`))) {
      normalized = normalized.slice(normalizedRoot.length).replace(/^\/+/, "");
    }
    const workspaceName = normalizedRoot.split("/").pop();
    if (workspaceName && normalized.toLowerCase().startsWith(`${workspaceName.toLowerCase()}/`)) {
      normalized = normalized.slice(workspaceName.length + 1);
    }
    if (normalized.toLowerCase().startsWith("workspace/")) {
      normalized = normalized.slice("workspace/".length);
    }
    return normalized;
  }

  function languageFromPath(path) {
    const extension = path.split(".").pop().toLowerCase();
    const languages = {
      js: "javascript",
      jsx: "javascript",
      json: "json",
      py: "python",
      ts: "typescript",
      tsx: "typescript",
      html: "html",
      css: "css",
      md: "markdown",
      ps1: "powershell",
      sh: "shell",
      sql: "sql",
      xml: "xml",
      yml: "yaml",
      yaml: "yaml",
    };
    return languages[extension] || "plaintext";
  }

  window.cmEditor = {
    editor: null,
    filePath: "main.py",
    pendingFilePath: null,
    pendingFileContent: null,
    bridgeReady: false,
    models: new Map(),
    loadedFiles: new Set(),
    suppressDirty: false,

    updateEditorStore(filePath, dirty = false) {
      if (!window.Alpine) {
        return;
      }
      const editorStore = window.Alpine.store("editor");
      const cmStore = window.Alpine.store("cm");
      if (filePath && !editorStore.openFiles.includes(filePath)) {
        editorStore.openFiles.push(filePath);
      }
      if (filePath) {
        cmStore.activeFile = filePath;
      }
      editorStore.dirtyFiles = editorStore.dirtyFiles.filter((path) => path !== filePath);
      if (dirty && filePath) {
        editorStore.dirtyFiles.push(filePath);
      }
    },

    setModelContent(filePath, content, clean = false) {
      const model = this.models.get(filePath);
      if (!model) {
        return;
      }
      this.suppressDirty = true;
      model.setValue(content);
      this.suppressDirty = false;
      this.loadedFiles.add(filePath);
      if (clean) {
        this.updateEditorStore(filePath, false);
      }
    },

    getOrCreateModel(filePath, content = "") {
      let model = this.models.get(filePath);
      if (!model) {
        const uri = window.monaco.Uri.parse(`inmemory://coding-machine/${encodeURIComponent(filePath)}`);
        model = window.monaco.editor.createModel(content, languageFromPath(filePath), uri);
        this.models.set(filePath, model);
      }
      return model;
    },

    init() {
      if (!window.require) {
        return;
      }

      window.require.config({
        paths: { vs: "https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs" },
      });
      window.require(["vs/editor/editor.main"], () => {
        this.editor = window.monaco.editor.create(document.getElementById("editor"), {
          model: this.getOrCreateModel(this.filePath),
          theme: "vs-dark",
          automaticLayout: true,
          fontSize: 14,
          minimap: { enabled: false },
          padding: { top: 18, bottom: 18 },
          scrollBeyondLastLine: false,
          tabSize: 4,
          wordWrap: "off",
          smoothScrolling: true,
          cursorBlinking: "smooth",
          cursorSmoothCaretAnimation: "on",
          bracketPairColorization: { enabled: true },
          guides: { bracketPairs: true, indentation: true },
          stickyScroll: { enabled: true },
          renderWhitespace: "selection",
        });
        this.editor.onDidChangeModelContent(() => {
          if (!this.suppressDirty && this.filePath) {
            this.updateEditorStore(this.filePath, true);
          }
        });
        const pendingFilePath = this.pendingFilePath;
        const pendingFileContent = this.pendingFileContent;
        this.pendingFilePath = null;
        this.pendingFileContent = null;
        if (pendingFilePath) {
          this.openFile(pendingFilePath, pendingFileContent);
        } else {
          this.loadFile();
        }
      });
    },

    async loadFile(filePath = this.filePath) {
      if (!this.editor) {
        return { success: false, error: "Editor is not ready" };
      }

      const normalizedFilePath = normalizeWorkspaceRelativePath(filePath);
      this.filePath = normalizedFilePath;
      const model = this.getOrCreateModel(normalizedFilePath);
      this.editor.setModel(model);
      if (this.loadedFiles.has(normalizedFilePath)) {
        return { success: true, path: normalizedFilePath, cached: true };
      }

      let content = null;
      const bridge = window.pywebview && window.pywebview.api;
      if (bridge && bridge.read_file) {
        try {
          const result = await bridge.read_file(normalizedFilePath);
          if (!result.success) {
            return { success: false, path: normalizedFilePath, error: result.error || "Unable to read file" };
          }
          content = result.content;
        } catch (error) {
          return { success: false, path: normalizedFilePath, error: String(error) };
        }
      } else if (window.pywebview) {
        return { success: true, path: normalizedFilePath, pending: true };
      } else {
        try {
          content = window.localStorage.getItem(`cm-file:${normalizedFilePath}`);
        } catch (error) {
          console.warn("Browser storage is unavailable", error);
        }
      }

      if (typeof content === "string") {
        this.setModelContent(normalizedFilePath, content, true);
      }
      return { success: true, path: normalizedFilePath };
    },

    async openFile(filePath, content = null) {
      if (!filePath) {
        return { success: false, error: "File path is required" };
      }
      const normalizedFilePath = normalizeWorkspaceRelativePath(filePath);
      this.filePath = normalizedFilePath;
      if (!this.editor) {
        this.pendingFilePath = normalizedFilePath;
        this.pendingFileContent = typeof content === "string" ? content : null;
        return { success: true, path: normalizedFilePath, pending: true };
      }
      const model = this.getOrCreateModel(normalizedFilePath);
      this.editor.setModel(model);
      this.filePath = normalizedFilePath;
      const dirty = window.Alpine && window.Alpine.store("editor").dirtyFiles.includes(normalizedFilePath);
      this.updateEditorStore(normalizedFilePath, dirty);
      if (model) {
        window.monaco.editor.setModelLanguage(model, languageFromPath(this.filePath));
      }
      if (typeof content === "string") {
        this.setModelContent(normalizedFilePath, content, true);
        return { success: true, path: this.filePath, source: "workspace_file_ready" };
      }
      return this.loadFile(normalizedFilePath);
    },

    async save() {
      if (!this.editor) {
        return { success: false, error: "Editor is not ready" };
      }
      if (!this.filePath) {
        return { success: false, error: "Open a file before saving" };
      }

      const content = this.editor.getValue();
      const bridge = window.pywebview && window.pywebview.api;
      if (bridge && bridge.write_file) {
        try {
          const result = await bridge.write_file(this.filePath, content);
          if (result && result.success) {
            this.updateEditorStore(this.filePath, false);
          }
          return result;
        } catch (error) {
          return { success: false, error: String(error) };
        }
      }

      try {
        window.localStorage.setItem(`cm-file:${this.filePath}`, content);
        this.updateEditorStore(this.filePath, false);
        return { success: true, local: true };
      } catch (error) {
        return { success: false, error: String(error) };
      }
    },

    async closeFile(filePath) {
      const normalizedFilePath = normalizeWorkspaceRelativePath(filePath);
      const editorStore = window.Alpine ? window.Alpine.store("editor") : null;
      if (editorStore && editorStore.dirtyFiles.includes(normalizedFilePath) && !window.confirm(`Discard unsaved changes in ${normalizedFilePath}?`)) {
        return false;
      }
      const openFiles = editorStore ? editorStore.openFiles : [];
      const closingIndex = openFiles.indexOf(normalizedFilePath);
      if (closingIndex >= 0) {
        openFiles.splice(closingIndex, 1);
      }
      if (editorStore) {
        editorStore.dirtyFiles = editorStore.dirtyFiles.filter((path) => path !== normalizedFilePath);
      }
      const model = this.models.get(normalizedFilePath);
      if (model) {
        model.dispose();
        this.models.delete(normalizedFilePath);
      }
      this.loadedFiles.delete(normalizedFilePath);
      if (openFiles.length) {
        const nextIndex = Math.min(closingIndex < 0 ? 0 : closingIndex, openFiles.length - 1);
        return this.openFile(openFiles[nextIndex]);
      }
      this.filePath = "";
      if (window.Alpine) {
        window.Alpine.store("cm").activeFile = "";
      }
      if (this.editor) {
        this.editor.setModel(null);
      }
      return true;
    },

    format() {
      if (!this.editor) {
        return false;
      }
      const action = this.editor.getAction("editor.action.formatDocument");
      if (!action) {
        return false;
      }
      void action.run();
      return true;
    },
  };

  window.addEventListener("pywebviewready", () => {
    window.cmEditor.bridgeReady = true;
    window.cmEditor.loadFile();
    if (window.cmAppInstance) {
      window.cmAppInstance.loadSessionContext();
      window.cmAppInstance.loadThemePreference();
      void window.cmAppInstance.refreshWorkspaceTree();
    }
  });

  window.cmSaveSessionBeforeExit = async () => {
    if (!window.cmAppInstance) {
      return false;
    }
    try {
      const result = await window.cmAppInstance.saveSession({ silent: true });
      return Boolean(result && result.success);
    } catch (error) {
      console.warn("Unable to save session before exit", error);
      return false;
    }
  };

  window.addEventListener("beforeunload", () => {
    void window.cmSaveSessionBeforeExit();
  });

  window.cmSqlEditor = {
    editor: null,
    loading: false,
    pendingValue: null,
    defaultValue: "SELECT * FROM sqlite_master LIMIT 100;",

    init() {
      if (this.editor || this.loading || !window.require) {
        return;
      }

      const container = document.getElementById("sql-editor");
      if (!container || container.offsetWidth === 0 || container.offsetHeight === 0) {
        return;
      }

      this.loading = true;
      window.require(["vs/editor/editor.main"], () => {
        this.loading = false;
        if (this.editor) {
          return;
        }
        const editorContainer = document.getElementById("sql-editor");
        if (!editorContainer) {
          return;
        }
        this.editor = window.monaco.editor.create(editorContainer, {
          value: this.pendingValue ?? this.defaultValue,
          language: "sql",
          theme: "vs-dark",
          automaticLayout: true,
          fontSize: 12,
          minimap: { enabled: false },
          lineNumbers: "on",
          scrollBeyondLastLine: false,
        });
        this.pendingValue = null;
      });
    },

    getValue() {
      return this.editor ? this.editor.getValue() : (this.pendingValue ?? "");
    },

    setValue(value) {
      if (this.editor) {
        this.editor.setValue(value);
      } else {
        this.pendingValue = String(value ?? "");
        this.init();
      }
    },
  };

  window.cmApp = function cmApp() {
    return {
      socket: null,
      draft: "",
      messages: [],
      sessionId: createSessionId(),
      sessionName: "New Session",
      sessionCreatedAt: new Date().toISOString(),
      sessionStatus: "Not saved",
      sessionContext: {
        model: "",
        projectPath: "",
      workspaceRoot: "",
      },
      workspaceTree: [],
      workspaceTreeOpen: false,
      workspaceTreeStatus: "",
      workspaceTreePath: "",
      workspaceSelectedPath: "",
      workspaceSelectedIsDirectory: false,
      workspaceClipboardPath: "",
      activeProjectPath: "",
      activeProjectName: "",
      savedSessions: [],
      sessionLoadOpen: false,
      sessionListStatus: "",
      sessionSavePromise: null,
      theme: readCachedTheme(),
      rightPanelZoom: readCachedPanelZoom(RIGHT_PANEL_ZOOM_PREFERENCE_KEY),
      notice: "",
      noticeTimer: null,
      workingTimer: null,
      workToken: 0,
      skills: [],
      selectedSkills: [],
      skillsOpen: false,
      tools: [],
      selectedTools: [],
      toolsOpen: false,
      autoCapabilities: true,
      capabilityRecommendation: null,
      streamingMessageIndex: null,
      requestActive: false,
      requestId: null,
      lastRequest: null,
      diffReview: null,
      approvalRequest: null,
      approvalPhrase: "",
      indexFileTypes: [],
      terminalInput: "",
      terminalOpening: false,
      pendingRunFile: null,
      runInProgress: false,
      runToken: null,
      runOutputBuffer: "",
      bottomTab: "terminal",
      handoffLimit: 8,
      rightPanel: "chat",
      dbForm: {
        connectionId: "local",
        dbType: "sqlite",
        connectionString: "cm.db",
      },
      dbStatus: "Connect a database to browse its schema.",
      dbStatusError: false,
      sourceControl: {
        branch: "",
        branches: [],
        remotes: [],
        history: [],
        remoteName: "origin",
        remoteBranch: "",
        selectedBranch: "",
        changes: [],
        diff: "",
        diffLines: [],
        diffPath: "",
        status: "Source control is not loaded.",
        error: "",
        isRepo: false,
        loading: false,
        statusRequestId: 0,
        statusTimeout: null,
        commitMessage: "",
        operationLoading: false,
      },
      mcp: {
        servers: [],
        selectedServerId: "",
        selectedServerName: "",
        transport: "stdio",
        command: "",
        args: "",
        url: "",
        envKeys: "",
        readOnly: true,
        tools: [],
        selectedToolName: "",
        arguments: "{}",
        result: "",
        status: "Select an optional MCP server. Servers remain disabled until you configure and connect them.",
        error: "",
        busy: false,
      },
      searchOpen: false,
      searchQuery: "",
      searchResults: [],
      searchPinnedResults: [],
      searchStatus: "Search the indexed workspace.",
      allFileTypes: true,
      paletteQuery: "",
      commands: [
        { name: "Open File", action: "triggerOpen" },
        { name: "Toggle Terminal", action: "toggleTerminal" },
      ],

      init() {
        window.cmAppInstance = this;
        window.cmEditor.init();
        window.cmSqlEditor.init();
        this.loadSkills();
        this.loadTools();
        this.setupChatRendering();
        this.setupResizablePanels();
        this.setupGlobalShortcuts();
        this.loadSessionContext();
        this.theme = applyTheme(this.theme);
        this.loadThemePreference();
        void this.refreshWorkspaceTree();
        this.socket = io("http://127.0.0.1:5000");

        this.socket.on("connect", () => {
          console.log("Connected to CM Backend");
          this.$store.cm.connected = true;
          this.$store.cm.activity = "Connected";
          this.terminalOpening = true;
          this.socket.emit("terminal_open", {});
          this.socket.emit("workspace_index_status");
          this.loadMcpServers();
        });

        this.socket.on("disconnect", () => {
          this.$store.cm.connected = false;
          this.$store.cm.activity = "Disconnected";
          if (this.requestActive) {
            this.messages.push({
              role: "agent",
              content: "Error: Connection to the backend was lost. The active request was cancelled.",
              copyLabel: "Copy",
            });
            this.streamingMessageIndex = null;
            this.requestActive = false;
            this.requestId = null;
            this.finishWork("agent", "Disconnected");
            void this.saveSession({ silent: true });
          }
          this.$store.cm.terminalConnected = false;
          this.terminalOpening = false;
          this.runInProgress = false;
          this.runToken = null;
          this.runOutputBuffer = "";
        });

        this.socket.on("agent_activity", (payload) => {
          if (payload.type === "handoff") {
            this.$store.cm.agentTrace.push({
              to: payload.to,
              reason: payload.reason || "",
              confidence: typeof payload.confidence === "number" ? payload.confidence : null,
              policy: payload.policy || null,
            });
            if (this.$store.cm.agentTrace.length > 100) {
              this.$store.cm.agentTrace.shift();
            }
            this.$store.cm.activity = `Handoff: ${payload.to}`;
            this.updateWorkProgress(`Handoff: ${payload.to}`, Math.min(70, 25 + this.$store.cm.agentTrace.length * 8), "agent");
          } else if (payload.type === "tool") {
            this.$store.cm.activity = `Running ${payload.name}`;
            this.updateWorkProgress(`Running ${payload.name}`, Math.min(86, Math.max(65, this.$store.cm.workingProgress + 5)), "agent");
          } else if (payload.type === "retry") {
            this.$store.cm.activity = `Retry ${payload.attempt}/${payload.max_retries}: ${payload.agent}`;
            this.updateWorkProgress(`Retrying ${payload.agent}`, Math.min(82, Math.max(45, this.$store.cm.workingProgress)), "agent");
          } else if (payload.type === "skills") {
            this.$store.cm.activity = `Skills: ${payload.skills.join(", ")}`;
            this.updateWorkProgress(`Loading skills`, 20, "agent");
          } else if (payload.type === "tools") {
            this.$store.cm.activity = `Tools: ${payload.tools.join(", ")}`;
            this.updateWorkProgress("Loading selected tools", 20, "agent");
          } else if (payload.type === "cancelled") {
            this.$store.cm.activity = "Cancelled";
            this.finishWork("agent", "Cancelled");
          } else {
            this.$store.cm.activity = "Thinking...";
            this.updateWorkProgress("Thinking", 15, "agent");
          }
        });

        this.socket.on("capability_recommendation", (payload) => {
          this.capabilityRecommendation = payload && payload.enabled ? payload : null;
          if (payload && payload.enabled) {
            this.$store.cm.activity = `Recommended: ${payload.agent}`;
            this.updateWorkProgress(`Routing to ${payload.agent}`, 12, "agent");
          }
        });

        this.socket.on("agent_message_chunk", (payload) => {
          if (this.streamingMessageIndex === null) {
            this.messages.push({ role: "agent", content: "", copyLabel: "Copy" });
            this.streamingMessageIndex = this.messages.length - 1;
          }
          this.messages[this.streamingMessageIndex].content += payload.content || "";
          this.updateWorkProgress("Streaming response", 90, "agent");
        });

        this.socket.on("agent_message_complete", (payload) => {
          if (this.streamingMessageIndex === null) {
            this.messages.push({ role: "agent", content: formatMessage(payload), copyLabel: "Copy" });
          } else if (typeof payload.content === "string") {
            this.messages[this.streamingMessageIndex].content = payload.content;
            this.messages[this.streamingMessageIndex].copyLabel = "Copy";
          }
          this.streamingMessageIndex = null;
          this.requestActive = false;
          this.requestId = null;
          this.$store.cm.activity = "Ready";
          this.finishWork("agent", "Complete");
          void this.saveSession({ silent: true });
        });

        this.socket.on("agent_error", (payload) => {
          this.messages.push({ role: "agent", content: `Error: ${payload.error || "Unknown agent error"}`, copyLabel: "Copy" });
          this.streamingMessageIndex = null;
          this.requestActive = false;
          this.requestId = null;
          this.$store.cm.activity = "Error";
          this.finishWork("agent", "Error");
          void this.saveSession({ silent: true });
        });

        this.socket.on("agent_cancelled", () => {
          this.streamingMessageIndex = null;
          this.requestActive = false;
          this.requestId = null;
          this.$store.cm.activity = "Cancelled";
          this.finishWork("agent", "Cancelled");
        });

        this.socket.on("agent_cancel_requested", () => {
          this.$store.cm.activity = "Cancelling...";
        });

        this.socket.on("agent_metrics", (payload) => {
          this.$store.cm.agentMetrics = {
            ...this.$store.cm.agentMetrics,
            ...payload,
          };
          if (payload.performance && payload.performance.success) {
            this.$store.cm.agentPerformance = payload.performance;
          }
          if (Array.isArray(payload.handoff_trace) && payload.handoff_trace.length) {
            this.$store.cm.agentTrace = payload.handoff_trace.map((handoff) => ({
              to: handoff.to,
              reason: handoff.reason || "",
              confidence: typeof handoff.confidence === "number" ? handoff.confidence : null,
              policy: handoff.policy || null,
            }));
          } else if (Array.isArray(payload.agent_trace) && payload.agent_trace.length) {
            this.$store.cm.agentTrace = payload.agent_trace.map((to) => ({ to, reason: "", confidence: null, policy: null }));
          }
        });

        this.socket.on("agent_performance", (payload) => {
          if (payload && payload.success) {
            this.$store.cm.agentPerformance = payload;
          }
        });

        this.socket.on("agent_plan", (payload) => {
          this.$store.cm.agentPlan = payload;
          this.$store.cm.activity = "Plan ready";
          this.updateWorkProgress("Planning implementation", 20, "agent");
        });

        this.socket.on("agent_state", (payload) => {
          this.$store.cm.agentState = payload || null;
        });

        this.socket.on("code_diff_review", (payload) => {
          this.diffReview = payload;
          this.rightPanel = "chat";
          this.$store.cm.activity = "Awaiting diff approval";
          this.updateWorkProgress(`Waiting for approval: ${payload.path}`, 65, "agent");
          this.showNotice(`Review ${payload.path} and choose Accept or Reject to continue.`);
          this.$nextTick(() => {
            const reviewCard = document.querySelector(".diff-review-card");
            if (reviewCard) {
              reviewCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
            }
          });
        });

        this.socket.on("code_diff_review_result", (payload) => {
          if (!payload.success) {
            this.diffReview = null;
            this.requestActive = false;
            this.requestId = null;
            this.$store.cm.activity = "Review unavailable";
            this.finishWork("agent", "Review unavailable");
            this.showNotice("This change review is no longer active.");
            return;
          }
          this.diffReview = null;
          this.updateWorkProgress(payload.accepted ? "Saving approved change" : "Change rejected", payload.accepted ? 80 : 100, "agent");
          this.showNotice(payload.accepted ? "Change accepted." : "Change rejected.");
        });

        this.socket.on("approval_required", (payload) => {
          this.approvalRequest = payload;
          this.approvalPhrase = "";
          this.showNotice(`${payload.category || "Action"} approval required.`);
        });

        this.socket.on("approval_action_result", (payload) => {
          if (!payload.success) {
            this.showNotice("This approval is no longer active or belongs to another client.");
            return;
          }
          this.approvalRequest = null;
          this.approvalPhrase = "";
          this.showNotice(payload.approved ? "Action approved." : "Action rejected.");
        });

        this.socket.on("code_presentation", (payload) => {
          this.$store.cm.codePresentation = payload;
          const filename = normalizeWorkspaceRelativePath(payload && payload.filename);
          if (filename) {
            void this.openGeneratedFile(filename);
          }
        });

        this.socket.on("workspace_file_changed", (payload) => {
          const filePath = normalizeWorkspaceRelativePath(payload && payload.path);
          if (filePath) {
            void this.openGeneratedFile(filePath);
          } else {
            void this.refreshWorkspaceTree();
          }
        });

        this.socket.on("workspace_file_ready", (payload) => {
          const filePath = normalizeWorkspaceRelativePath(payload && payload.path);
          if (filePath) {
            void this.openGeneratedFile(filePath, typeof payload.content === "string" ? payload.content : null);
          }
        });

        this.socket.on("project_created", (payload) => {
          this.activeProjectPath = normalizeWorkspaceRelativePath(payload && payload.path);
          this.activeProjectName = String((payload && payload.name) || this.activeProjectPath.split("/").pop() || "");
          this.showNotice(`Created project ${this.activeProjectName}`);
          if (this.activeProjectPath) {
            void this.refreshWorkspaceTree(this.activeProjectPath);
          }
        });

        this.socket.on("agent_response", (payload) => {
          this.messages.push({ role: "agent", content: formatMessage(payload) });
        });

        this.socket.on("indexing_started", (payload) => {
          this.$store.cm.indexingStatus = "Indexing codebase...";
          this.$store.cm.indexingActive = true;
          this.$store.cm.indexingProgress = { current: 0, total: 0, indexed: 0, skipped: 0, errors: 0 };
          this.$store.cm.indexingErrors = [];
          this.beginWork("Indexing workspace", 10, "indexing");
        });

        this.socket.on("indexing_progress", (payload) => {
          this.$store.cm.indexingActive = true;
          this.$store.cm.indexingProgress = {
            ...this.$store.cm.indexingProgress,
            ...payload,
          };
          const total = Number(payload.total || 0);
          const current = Number(payload.current || 0);
          const progress = total ? Math.round((current / total) * 100) : 10;
          this.$store.cm.indexingStatus = total ? `Indexing ${current}/${total}` : "Indexing codebase...";
          this.updateWorkProgress(payload.path ? `Indexing ${payload.path}` : "Indexing workspace", progress, "indexing");
        });

        this.socket.on("indexing_error", (payload) => {
          const error = String(payload.error || "Unknown indexing error");
          this.$store.cm.indexingErrors.push(error);
          this.$store.cm.indexingStatus = `Indexing error: ${error}`;
        });

        this.socket.on("indexing_complete", (payload) => {
          this.$store.cm.indexingStatus = payload.status === "complete"
            ? `Indexed ${payload.indexed || 0} file(s)`
            : `Indexing failed: ${payload.error || "Unknown error"}`;
          this.$store.cm.indexingActive = false;
          this.$store.cm.indexingProgress = {
            ...this.$store.cm.indexingProgress,
            ...payload,
          };
          this.$store.cm.indexingErrors = payload.errors || this.$store.cm.indexingErrors;
          this.finishWork("indexing", payload.status === "complete" ? "Index complete" : "Index failed");
        });

        this.socket.on("indexing_status", (payload) => {
          this.$store.cm.indexingActive = payload.status === "started" || payload.status === "running";
          this.$store.cm.indexingProgress = { ...this.$store.cm.indexingProgress, ...payload };
          if (payload.status === "complete") {
            this.$store.cm.indexingStatus = `Indexed ${payload.indexed || 0} file(s)`;
          } else if (payload.status === "error") {
            this.$store.cm.indexingStatus = `Indexing failed: ${payload.error || "Unknown error"}`;
          }
        });

        this.socket.on("codebase_search_results", (payload) => {
          const pinnedResults = this.searchPinnedResults || [];
          const pinnedPaths = new Set(pinnedResults.map((result) => result.metadata && result.metadata.file_path));
          const semanticResults = (payload.results || []).filter((result) => !pinnedPaths.has(result.metadata && result.metadata.file_path));
          this.searchResults = [...pinnedResults, ...semanticResults];
          this.searchStatus = payload.success
            ? `${this.searchResults.length} result(s)`
            : payload.error || "Search failed";
        });

        this.socket.on("db_connection_result", (payload) => {
          this.dbStatusError = !payload.success;
          if (!payload.success) {
            this.dbStatus = `Connection failed: ${payload.error || "Unknown error"}`;
            return;
          }

          const connections = this.$store.cm.dbConnections.filter(
            (connection) => connection.connection_id !== payload.connection_id,
          );
          connections.push(payload);
          this.$store.cm.dbConnections = connections;
          this.$store.cm.activeDbConnection = payload.connection_id;
          this.dbStatus = `Connected to ${payload.connection_id}`;
          this.dbStatusError = false;
          this.socket.emit("db_list_tables", { connection_id: payload.connection_id });
        });

        this.socket.on("db_tables", (payload) => {
          if (!payload.success) {
            this.dbStatus = `Schema error: ${payload.error || "Unknown error"}`;
            this.dbStatusError = true;
            return;
          }
          this.$store.cm.dbTables = payload.tables || [];
          this.dbStatus = `${this.$store.cm.dbTables.length} table(s) loaded`;
          this.dbStatusError = false;
        });

        this.socket.on("db_query_result", (payload) => {
          this.$store.cm.dbResults = payload.success
            ? payload
            : { columns: ["error"], rows: [{ error: payload.error || "Query failed" }] };
          this.dbStatusError = !payload.success;
          this.dbStatus = payload.success
            ? `${payload.rows.length} row(s) returned`
            : `Query error: ${payload.error || "Unknown error"}`;
          if (payload.success && this.$store.cm.activeDbConnection) {
            this.socket.emit("db_list_tables", { connection_id: this.$store.cm.activeDbConnection });
          }
        });

        this.socket.on("source_control_status_result", (payload) => {
          if (payload.request_id && payload.request_id !== this.sourceControl.statusRequestId) {
            return;
          }
          if (this.sourceControl.statusTimeout) {
            window.clearTimeout(this.sourceControl.statusTimeout);
            this.sourceControl.statusTimeout = null;
          }
          this.sourceControl.loading = false;
          this.sourceControl.isRepo = Boolean(payload.is_repo);
          this.sourceControl.branch = payload.branch || "";
          this.sourceControl.branches = payload.branches || [];
          this.sourceControl.remotes = payload.remotes || [];
          this.sourceControl.selectedBranch = payload.current_branch || this.sourceControl.selectedBranch;
          if (this.sourceControl.remotes.length && !this.sourceControl.remotes.some((remote) => remote.name === this.sourceControl.remoteName)) {
            this.sourceControl.remoteName = this.sourceControl.remotes[0].name;
          }
          if (!this.sourceControl.remoteBranch) {
            this.sourceControl.remoteBranch = payload.current_branch || "";
          }
          if (!this.sourceControl.remoteName && this.sourceControl.remotes.length) {
            this.sourceControl.remoteName = this.sourceControl.remotes[0].name;
          }
          this.sourceControl.changes = payload.changes || [];
          this.sourceControl.error = payload.success ? "" : (payload.error || "Source control unavailable.");
          this.sourceControl.status = payload.is_repo
            ? `${this.sourceControl.changes.length} change(s)`
            : (payload.error || "No Git repository found.");
          if (payload.is_repo) {
            this.loadSourceHistory();
          }
        });

        this.socket.on("source_control_diff_result", (payload) => {
          if (!payload.success) {
            this.sourceControl.error = payload.error || "Unable to load diff.";
            return;
          }
          this.sourceControl.diffPath = payload.path || "";
          this.sourceControl.diff = payload.diff || "No tracked diff for this file.";
          this.sourceControl.diffLines = payload.diffLines || payload.diff_lines || [];
        });

        this.socket.on("source_control_history_result", (payload) => {
          this.sourceControl.history = payload.success ? (payload.history || []) : [];
          if (!payload.success && payload.error) {
            this.sourceControl.error = payload.error;
          }
        });

        this.socket.on("source_control_action_result", (payload) => {
        if (!payload.success) {
            this.sourceControl.operationLoading = false;
            this.sourceControl.error = payload.error || "Source control action failed.";
            this.showNotice(this.sourceControl.error);
            return;
          }
          this.sourceControl.error = "";
          this.sourceControl.operationLoading = false;
          this.showNotice("Source control action completed.");
          this.refreshSourceControl();
          this.loadSourceHistory();
        });

        this.socket.on("mcp_servers", (payload) => {
          if (!payload.success) {
            this.mcp.error = payload.error || "Unable to load MCP servers.";
            return;
          }
          this.applyMcpServers(payload.servers || []);
        });

        this.socket.on("mcp_configure_result", (payload) => {
          this.mcp.busy = false;
          if (!payload.success) {
            this.mcp.error = payload.error || "Unable to save MCP configuration.";
            return;
          }
          this.applyMcpServers(payload.servers || []);
          this.mcp.status = "Configuration saved. Connect to discover tools.";
          this.mcp.error = "";
        });

        this.socket.on("mcp_connect_result", (payload) => {
          this.mcp.busy = false;
          this.applyMcpServers(payload.servers || []);
          if (!payload.success) {
            this.mcp.error = payload.error || "Unable to connect to MCP server.";
            return;
          }
          this.mcp.tools = payload.tools || [];
          this.mcp.status = `Connected. ${this.mcp.tools.length} tool(s) discovered.`;
          this.mcp.error = "";
          this.selectMcpTool(this.mcp.tools.find((tool) => tool.allowed) || this.mcp.tools[0]);
        });

        this.socket.on("mcp_disconnect_result", (payload) => {
          this.mcp.busy = false;
          this.applyMcpServers(payload.servers || []);
          this.mcp.tools = [];
          this.mcp.selectedToolName = "";
          this.mcp.status = payload.success ? "MCP server disconnected." : (payload.error || "Unable to disconnect MCP server.");
          this.mcp.error = payload.success ? "" : this.mcp.status;
        });

        this.socket.on("mcp_tools", (payload) => {
          if (payload.success) {
            this.mcp.tools = payload.tools || [];
          } else {
            this.mcp.error = payload.error || "Unable to list MCP tools.";
          }
        });

        this.socket.on("mcp_tool_result", (payload) => {
          this.mcp.busy = false;
          this.mcp.result = JSON.stringify(payload, null, 2);
          this.mcp.error = payload.success ? "" : (payload.error || "MCP tool call failed.");
          this.mcp.status = payload.success ? `Completed ${payload.tool || "MCP tool"}.` : this.mcp.status;
        });

        this.socket.on("terminal_ready", (payload) => {
          this.terminalOpening = false;
          this.$store.cm.terminalSessionId = payload.session_id;
          this.$store.cm.terminalConnected = true;
          this.addTerminalLine("system", "Terminal session ready.\n");
          if (this.pendingRunFile) {
            const pendingRunFile = this.pendingRunFile;
            this.pendingRunFile = null;
            this.runActiveFile(pendingRunFile);
          }
        });

        this.socket.on("terminal_output", (payload) => {
          if (payload.session_id !== this.$store.cm.terminalSessionId) {
            return;
          }
          const data = String(payload.data || "");
          if (this.runToken) {
            this.runOutputBuffer = (this.runOutputBuffer + data).slice(-512);
            if (this.runOutputBuffer.includes(this.runToken)) {
              const lastLine = this.$store.cm.terminalLines[this.$store.cm.terminalLines.length - 1];
              if (lastLine && lastLine.type === "stdout") {
                const tokenStart = String(lastLine.data).lastIndexOf("CM_RUN_COMPLETE_");
                if (tokenStart >= 0) {
                  lastLine.data = String(lastLine.data).slice(0, tokenStart);
                }
              }
              this.runInProgress = false;
              this.runToken = null;
              this.runOutputBuffer = "";
              this.$store.cm.activity = "Ready";
              return;
            }
          }
          this.addTerminalLine(payload.type, data);
          const lastLine = this.$store.cm.terminalLines[this.$store.cm.terminalLines.length - 1];
          if (payload.type === "stdout" && lastLine && String(lastLine.data).trimEnd().endsWith("Name:")) {
            this.$store.cm.activity = "Program waiting for input";
            this.$nextTick(() => this.$refs.terminalInput && this.$refs.terminalInput.focus());
          }
        });

        this.socket.on("terminal_error", (payload) => {
          this.addTerminalLine("stderr", `${payload.error || "Terminal error"}\n`);
        });

        this.socket.on("terminal_command_result", (payload) => {
          if (!payload.success) {
            this.runInProgress = false;
            this.runToken = null;
            this.runOutputBuffer = "";
            this.addTerminalLine("stderr", `${payload.error || "Unable to execute terminal command"}\n`);
          }
        });

        this.socket.on("terminal_closed", () => {
          this.$store.cm.terminalConnected = false;
          this.$store.cm.terminalSessionId = null;
          this.runInProgress = false;
          this.runToken = null;
          this.runOutputBuffer = "";
          this.addTerminalLine("system", "Terminal session closed.\n");
        });
      },

      async loadSkills() {
        try {
          const response = await fetch("/api/skills");
          if (!response.ok) {
            throw new Error(`Skill request failed: ${response.status}`);
          }
          const payload = await response.json();
          this.skills = payload.skills || [];
        } catch (error) {
          console.warn("Unable to load CM skills", error);
          this.skills = [];
        }
      },

      async loadTools() {
        try {
          const response = await fetch("/api/tools");
          if (!response.ok) {
            throw new Error(`Tool request failed: ${response.status}`);
          }
          const payload = await response.json();
          this.tools = payload.tools || [];
        } catch (error) {
          console.warn("Unable to load MCM tools", error);
          this.tools = [];
        }
      },

      setupChatRendering() {
        const container = this.$refs.chatMessages;
        if (!container || typeof MutationObserver === "undefined") {
          return;
        }
        this.chatMutationObserver = new MutationObserver(() => this.highlightAllMessages());
        this.chatMutationObserver.observe(container, { childList: true, subtree: true, characterData: true });
        this.$nextTick(() => this.highlightAllMessages());
      },

      highlightAllMessages() {
        if (!window.hljs || !this.$refs.chatMessages) {
          return;
        }
        this.$refs.chatMessages.querySelectorAll(".message-content pre code:not(.hljs)").forEach((block) => {
          window.hljs.highlightElement(block);
        });
      },

      renderMessage(message) {
        const content = String(message && message.content ? message.content : "");
        if (!content) {
          return "";
        }
        if (message.role === "user" || !window.marked || !window.DOMPurify) {
          return `<div class="message-fallback">${escapeHtml(content).replaceAll("\n", "<br>")}</div>`;
          return `<div class="message-fallback">${escapeHtml(content).replaceAll("\n", "<br>")}</div>`;
        }
        const rendered = window.marked.parse(content, { breaks: true, gfm: true });
        return window.DOMPurify.sanitize(rendered);
      },

      async copyMessage(message) {
        const content = String(message && message.content ? message.content : "");
        if (!content) {
          return;
        }
        try {
          const html = this.renderMessage(message);
          if (navigator.clipboard && window.ClipboardItem && navigator.clipboard.write) {
            await navigator.clipboard.write([
              new ClipboardItem({
                "text/plain": new Blob([content], { type: "text/plain" }),
                "text/html": new Blob([html], { type: "text/html" }),
              }),
            ]);
          } else if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(content);
          } else {
            const textarea = document.createElement("textarea");
            textarea.value = content;
            textarea.setAttribute("readonly", "");
            textarea.style.position = "fixed";
            textarea.style.opacity = "0";
            document.body.appendChild(textarea);
            try {
              textarea.select();
              if (!document.execCommand("copy")) {
                throw new Error("Clipboard copy was rejected");
              }
            } finally {
              textarea.remove();
            }
          }
          message.copyLabel = "Copied!";
          window.setTimeout(() => {
            message.copyLabel = "Copy";
          }, 1600);
        } catch (error) {
          message.copyLabel = "Copy failed";
          window.setTimeout(() => {
            message.copyLabel = "Copy";
          }, 1800);
          console.warn("Unable to copy assistant response", error);
        }
      },

      async loadSessionContext() {
        const bridge = window.pywebview && window.pywebview.api;
        if (!bridge || !bridge.get_app_context) {
          return;
        }
        try {
          const result = await bridge.get_app_context();
          if (result && result.success) {
            this.sessionContext = {
              model: result.model || "",
              projectPath: result.project_path || "",
              workspaceRoot: result.workspace_root || "",
            };
          }
        } catch (error) {
          console.warn("Unable to load application session context", error);
        }
      },

      async openWorkspace() {
        const bridge = window.pywebview && window.pywebview.api;
        if (!bridge || !bridge.choose_workspace) {
          this.showNotice("Open Workspace is available in the desktop application.");
          return;
        }
        try {
          const result = await bridge.choose_workspace();
          if (result && result.success) {
            this.sessionContext.workspaceRoot = result.workspace_root;
            this.workspaceTreeStatus = "Workspace saved. Restart CM to apply it.";
            this.showNotice("Workspace saved. Restart CM to apply the new folder.");
          } else if (result && !result.cancelled) {
            this.showNotice(`Unable to change workspace: ${result.error || "Unknown error"}`);
          }
        } catch (error) {
          this.showNotice(`Unable to change workspace: ${error}`);
        }
      },

      async loadThemePreference() {
        let theme = readCachedTheme();
        const bridge = window.pywebview && window.pywebview.api;
        if (bridge && bridge.get_preference) {
          try {
            const result = await bridge.get_preference(THEME_PREFERENCE_KEY, theme);
            if (result && result.success && VALID_THEMES.has(result.value)) {
              theme = result.value;
            }
          } catch (error) {
            console.warn("Unable to load theme preference", error);
          }
        }
        this.theme = applyTheme(theme);
        return this.theme;
      },

      rightPanelZoomStyle() {
        return { "--panel-scale": this.rightPanelZoom / 100 };
      },

      changeRightPanelZoom(delta) {
        this.rightPanelZoom = Math.max(PANEL_ZOOM_MIN, Math.min(PANEL_ZOOM_MAX, this.rightPanelZoom + delta));
        cachePanelZoom(RIGHT_PANEL_ZOOM_PREFERENCE_KEY, this.rightPanelZoom);
        this.showNotice(`Right panel zoom: ${this.rightPanelZoom}%`);
      },

      resetRightPanelZoom() {
        this.rightPanelZoom = PANEL_ZOOM_MIN;
        cachePanelZoom(RIGHT_PANEL_ZOOM_PREFERENCE_KEY, PANEL_ZOOM_MIN);
        this.showNotice("Right panel zoom reset to 100%.");
      },

      async toggleTheme() {
        const nextTheme = this.theme === "dark" ? "colorful" : "dark";
        this.theme = applyTheme(nextTheme);
        const bridge = window.pywebview && window.pywebview.api;
        if (bridge && bridge.set_preference) {
          try {
            const result = await bridge.set_preference(THEME_PREFERENCE_KEY, this.theme);
            if (!result || !result.success) {
              console.warn("Unable to save theme preference", result && result.error);
            }
          } catch (error) {
            console.warn("Unable to save theme preference", error);
          }
        }
        return this.theme;
      },

      buildSessionPayload() {
        const now = new Date().toISOString();
        return {
          session_id: this.sessionId,
          name: this.sessionName || this.sessionId,
          timestamp: this.sessionCreatedAt,
          created_at: this.sessionCreatedAt,
          updated_at: now,
          user_prompts: this.messages.filter((message) => message.role === "user").map((message) => message.content),
          assistant_responses: this.messages.filter((message) => message.role === "agent").map((message) => message.content),
          conversation_history: this.messages.map((message) => ({ role: message.role, content: message.content })),
          model_name: this.sessionContext.model || "unknown",
          project_path: this.sessionContext.projectPath || "",
          current_workspace: this.sessionContext.workspaceRoot || "",
          conversation_metadata: {
            active_skills: [...this.selectedSkills],
            active_tools: [...this.selectedTools],
            auto_capabilities: this.autoCapabilities,
            handoff_limit: this.handoffLimit,
            message_count: this.messages.length,
            right_panel: this.rightPanel,
            active_project_path: this.activeProjectPath,
          },
        };
      },

      async saveSession({ silent = false } = {}) {
        if (!silent && this.sessionName === "New Session" && this.messages.length) {
          const requestedName = window.prompt("Session name", this.sessionName);
          if (requestedName === null) {
            return { success: false, cancelled: true };
          }
          this.sessionName = requestedName.trim() || this.sessionName;
        }
        const bridge = window.pywebview && window.pywebview.api;
        if (!bridge || !bridge.save_session) {
          if (!silent) {
            this.sessionStatus = "Desktop session storage unavailable";
          }
          return { success: false, error: "Desktop session storage unavailable" };
        }
        const payload = this.buildSessionPayload();
        const request = () => bridge.save_session(payload);
        this.sessionSavePromise = (this.sessionSavePromise || Promise.resolve()).catch(() => {}).then(request);
        try {
          const result = await this.sessionSavePromise;
          if (result && result.success) {
            this.sessionStatus = `Saved ${new Date().toLocaleTimeString()}`;
          } else if (!silent) {
            this.sessionStatus = `Save failed: ${(result && result.error) || "Unknown error"}`;
          }
          return result;
        } catch (error) {
          if (!silent) {
            this.sessionStatus = `Save failed: ${error}`;
          }
          return { success: false, error: String(error) };
        } finally {
          this.sessionSavePromise = null;
        }
      },

      async openLoadSession() {
        const bridge = window.pywebview && window.pywebview.api;
        if (!bridge || !bridge.list_sessions) {
          this.sessionListStatus = "Desktop session storage unavailable.";
          this.sessionLoadOpen = true;
          return;
        }
        this.sessionListStatus = "Loading sessions...";
        this.sessionLoadOpen = true;
        try {
          const result = await bridge.list_sessions();
          if (!result.success) {
            this.sessionListStatus = result.error || "Unable to list sessions.";
            this.savedSessions = [];
            return;
          }
          this.savedSessions = result.sessions || [];
          this.sessionListStatus = this.savedSessions.length ? "Select a session to restore." : "No saved sessions found.";
        } catch (error) {
          this.savedSessions = [];
          this.sessionListStatus = `Unable to list sessions: ${error}`;
        }
      },

      async loadSession(sessionId) {
        const bridge = window.pywebview && window.pywebview.api;
        if (!bridge || !bridge.load_session) {
          this.sessionListStatus = "Desktop session storage unavailable.";
          return;
        }
        this.sessionListStatus = "Loading...";
        try {
          const result = await bridge.load_session(sessionId);
          if (!result.success) {
            this.sessionListStatus = result.error || "Unable to load session.";
            return;
          }
          const session = result.session || {};
          const history = Array.isArray(session.conversation_history) ? session.conversation_history : [];
          this.sessionId = session.session_id || sessionId;
          this.sessionName = session.name || this.sessionId;
          this.sessionCreatedAt = session.created_at || session.timestamp || new Date().toISOString();
          this.messages = history
            .filter((message) => message && (message.role === "user" || message.role === "agent"))
            .map((message) => ({ role: message.role, content: String(message.content || ""), copyLabel: message.role === "agent" ? "Copy" : undefined }));
          const metadata = session.conversation_metadata || {};
          if (Array.isArray(metadata.active_skills)) {
            this.selectedSkills = metadata.active_skills;
          }
          if (Array.isArray(metadata.active_tools)) {
            this.selectedTools = metadata.active_tools;
          }
          if (typeof metadata.auto_capabilities === "boolean") {
            this.autoCapabilities = metadata.auto_capabilities;
          }
          if (metadata.handoff_limit) {
            this.handoffLimit = Number(metadata.handoff_limit);
          }
          if (metadata.active_project_path) {
            this.activeProjectPath = normalizeWorkspaceRelativePath(metadata.active_project_path);
            this.activeProjectName = this.activeProjectPath.split("/").pop() || "";
            void this.refreshWorkspaceTree(this.activeProjectPath);
          }
          this.sessionStatus = `Loaded ${new Date().toLocaleTimeString()}`;
          this.sessionLoadOpen = false;
          this.$nextTick(() => this.highlightAllMessages());
        } catch (error) {
          this.sessionListStatus = `Unable to load session: ${error}`;
        }
      },

      newSession() {
        if (this.messages.length && !window.confirm("Start a new session? Unsaved conversation content will be cleared.")) {
          return;
        }
        this.sessionId = createSessionId();
        this.sessionName = "New Session";
        this.sessionCreatedAt = new Date().toISOString();
        this.sessionStatus = "Not saved";
        this.messages = [];
        this.streamingMessageIndex = null;
        this.clearAgentTrace();
        this.$store.cm.agentPlan = null;
      },

      async saveFile() {
        const result = await window.cmEditor.save();
        if (result && result.success) {
          this.showNotice("Saved " + window.cmEditor.filePath);
        } else {
          this.showNotice("Save failed: " + ((result && result.error) || "Unable to save file"));
        }
        return result;
      },

      formatEditor() {
        if (!window.cmEditor.format()) {
          this.showNotice("Formatting is not available for this file type.");
        }
      },

      closeEditorFile(filePath) {
        void window.cmEditor.closeFile(filePath);
      },

      async activateEditorFile(filePath) {
        const normalized = normalizeWorkspaceRelativePath(filePath);
        const parts = normalized.split("/");
        if (parts.length > 1) {
          this.activeProjectPath = parts.slice(0, -1).join("/");
          this.activeProjectName = this.activeProjectPath.split("/").pop() || "";
        }
        const result = await window.cmEditor.openFile(normalized);
        if (!result.success) {
          this.showNotice(`Unable to open file: ${result.error}`);
        }
        return result;
      },

      setupResizablePanels() {
        const shell = document.querySelector(".ide-shell");
        if (!shell) {
          return;
        }
        let activeResizer = null;

        const stopResize = () => {
          activeResizer = null;
          document.body.classList.remove("is-resizing");
        };

        document.querySelectorAll(".resizer").forEach((resizer) => {
          resizer.addEventListener("mousedown", (event) => {
            event.preventDefault();
            activeResizer = resizer.id;
            document.body.classList.add("is-resizing");
          });
        });

        window.addEventListener("mousemove", (event) => {
          if (!activeResizer) {
            return;
          }
          if (activeResizer === "resizer-left") {
            const width = Math.max(50, Math.min(320, event.clientX));
            shell.style.setProperty("--sidebar-width", `${width}px`);
          } else if (activeResizer === "resizer-bottom") {
            const height = Math.max(120, Math.min(520, window.innerHeight - event.clientY));
            shell.style.setProperty("--bottom-height", `${height}px`);
          }
        });
        window.addEventListener("mouseup", stopResize);
      },

      setupGlobalShortcuts() {
        window.addEventListener("keydown", (event) => {
          const key = event.key.toLowerCase();
          if (event.key === "Escape") {
            this.$store.ui.showPalette = false;
            return;
          }
          if (event.ctrlKey && event.shiftKey && key === "p") {
            event.preventDefault();
            if (this.$store.ui.showPalette) {
              this.$store.ui.showPalette = false;
              this.paletteQuery = "";
            } else {
              this.openCommandPalette();
            }
          } else if (event.ctrlKey && event.shiftKey && key === "f") {
            event.preventDefault();
            this.toggleSearchPanel();
          } else if (event.ctrlKey && key === "s") {
            event.preventDefault();
            this.saveFile();
          } else if (event.ctrlKey && key === "l") {
            event.preventDefault();
            this.$nextTick(() => this.$refs.chatInput && this.$refs.chatInput.focus());
          } else if (event.ctrlKey && event.key === "F5") {
            event.preventDefault();
            this.runActiveFile();
          }
        });
      },

      filteredCommands() {
        const query = this.paletteQuery.trim().toLowerCase();
        return query ? this.commands.filter((command) => command.name.toLowerCase().includes(query)) : this.commands;
      },

      openCommandPalette() {
        this.$store.ui.showPalette = true;
        this.paletteQuery = "";
        this.$nextTick(() => this.$refs.paletteInput && this.$refs.paletteInput.focus());
      },

      runPaletteCommand(command) {
        if (command && typeof this[command.action] === "function") {
          this[command.action]();
        }
        this.$store.ui.showPalette = false;
        this.paletteQuery = "";
      },

      triggerOpen() {
        this.toggleSearchPanel();
      },

      toggleTerminal() {
        this.$store.ui.showTerminal = !this.$store.ui.showTerminal;
      },

      setBottomTab(tab) {
        if (["terminal", "output", "problems"].includes(tab)) {
          this.bottomTab = tab;
        }
      },

      beginWork(name, progress, source) {
        this.workToken += 1;
        this.updateWorkProgress(name, progress, source);
      },

      updateWorkProgress(name, progress, source) {
        const work = this.$store.cm;
        if (this.workingTimer) {
          window.clearTimeout(this.workingTimer);
          this.workingTimer = null;
        }
        work.workingActive = true;
        work.workingName = name;
        work.workingProgress = Math.max(0, Math.min(100, Math.round(progress)));
        work.workingSource = source;
      },

      finishWork(source, name) {
        const work = this.$store.cm;
        if (!work.workingActive || work.workingSource !== source) {
          return;
        }
        if (this.workingTimer) {
          window.clearTimeout(this.workingTimer);
        }
        work.workingName = name;
        work.workingProgress = 100;
        const token = this.workToken;
        this.workingTimer = window.setTimeout(() => {
          if (this.workToken === token && work.workingSource === source) {
            work.workingActive = false;
            work.workingName = "Ready";
            work.workingProgress = 0;
            work.workingSource = "";
          }
          this.workingTimer = null;
        }, 1200);
      },

      showNotice(message) {
        this.notice = message;
        if (this.noticeTimer) {
          window.clearTimeout(this.noticeTimer);
        }
        this.noticeTimer = window.setTimeout(() => {
          this.notice = "";
          this.noticeTimer = null;
        }, 3200);
      },

      useQuickStart(prompt) {
        this.draft = prompt;
        this.rightPanel = "chat";
        this.$nextTick(() => this.$refs.chatInput && this.$refs.chatInput.focus());
      },

      toggleSourceControl() {
        this.rightPanel = "source";
        this.refreshSourceControl();
        this.loadSourceHistory();
      },

      toggleMcpPanel() {
        this.rightPanel = "mcp";
        this.loadMcpServers();
      },

      openSettingsPanel() {
        this.rightPanel = "settings";
        this.skillsOpen = false;
        this.toolsOpen = false;
      },

      openSkillsMenu() {
        if (this.skillsOpen && this.rightPanel === "chat") {
          this.skillsOpen = false;
          return;
        }
        this.rightPanel = "chat";
        this.skillsOpen = true;
        this.toolsOpen = false;
        this.showNotice(`${this.skills.length} Skills available. Selected Skills guide the next agent request.`);
        this.$nextTick(() => {
          const skillToggle = document.querySelector(".skill-toggle");
          if (skillToggle) {
            skillToggle.focus();
          }
        });
      },

      openToolsMenu() {
        this.rightPanel = "chat";
        this.skillsOpen = false;
        this.toolsOpen = true;
        this.showNotice(`${this.tools.length} built-in tools available. Selected tools are added to the next agent request.`);
        this.$nextTick(() => {
          const toolToggle = document.querySelector(".tool-toggle");
          if (toolToggle) {
            toolToggle.focus();
          }
        });
      },

      loadMcpServers() {
        if (this.socket) {
          this.socket.emit("mcp_list_servers");
        }
      },

      applyMcpServers(servers) {
        this.mcp.servers = Array.isArray(servers) ? servers : [];
        const selected = this.mcp.servers.find((server) => server.server_id === this.mcp.selectedServerId)
          || this.mcp.servers[0];
        if (selected) {
          this.selectMcpServer(selected.server_id, false);
        }
      },

      selectMcpServer(serverId, requestTools = true) {
        const server = this.mcp.servers.find((item) => item.server_id === serverId);
        if (!server) {
          return;
        }
        this.mcp.selectedServerId = server.server_id;
        this.mcp.selectedServerName = server.name;
        this.mcp.transport = server.transport || "stdio";
        this.mcp.command = server.command || "";
        this.mcp.args = (server.args || []).join(" ");
        this.mcp.url = server.url || "";
        this.mcp.envKeys = (server.env_keys || []).join(", ");
        this.mcp.readOnly = server.read_only !== false;
        this.mcp.tools = server.tools || [];
        this.mcp.selectedToolName = "";
        this.mcp.result = "";
        if (requestTools && server.status === "connected" && this.socket) {
          this.socket.emit("mcp_list_tools", { server_id: server.server_id });
        }
      },

      saveMcpConfiguration() {
        if (!this.socket || !this.mcp.selectedServerId) {
          return;
        }
        this.mcp.busy = true;
        this.mcp.error = "";
        const args = this.mcp.args.match(/(?:[^\s"]+|"[^"]*")+/g) || [];
        this.socket.emit("mcp_configure_server", {
          server_id: this.mcp.selectedServerId,
          transport: this.mcp.transport,
          command: this.mcp.command,
          args: args.map((item) => item.replace(/^"|"$/g, "")),
          url: this.mcp.url,
          env_keys: this.mcp.envKeys,
          read_only: this.mcp.readOnly,
          enabled: true,
        });
      },

      connectMcpServer() {
        if (!this.socket || !this.mcp.selectedServerId) {
          return;
        }
        this.mcp.busy = true;
        this.mcp.error = "";
        this.socket.emit("mcp_connect", { server_id: this.mcp.selectedServerId });
      },

      disconnectMcpServer() {
        if (!this.socket || !this.mcp.selectedServerId) {
          return;
        }
        this.mcp.busy = true;
        this.socket.emit("mcp_disconnect", { server_id: this.mcp.selectedServerId });
      },

      selectMcpTool(tool) {
        if (!tool) {
          this.mcp.selectedToolName = "";
          return;
        }
        this.mcp.selectedToolName = tool.name;
        this.mcp.arguments = "{}";
        this.mcp.result = "";
      },

      callMcpTool() {
        if (!this.socket || !this.mcp.selectedServerId || !this.mcp.selectedToolName) {
          return;
        }
        let arguments;
        try {
          arguments = JSON.parse(this.mcp.arguments || "{}");
        } catch (error) {
          this.mcp.error = "MCP tool arguments must be valid JSON.";
          return;
        }
        if (!arguments || Array.isArray(arguments) || typeof arguments !== "object") {
          this.mcp.error = "MCP tool arguments must be a JSON object.";
          return;
        }
        this.mcp.busy = true;
        this.mcp.error = "";
        this.socket.emit("mcp_call_tool", {
          server_id: this.mcp.selectedServerId,
          tool_name: this.mcp.selectedToolName,
          arguments,
        });
      },

      refreshSourceControl() {
        if (!this.socket) {
          this.sourceControl.status = "Backend is not connected.";
          return;
        }
        if (this.sourceControl.statusTimeout) {
          window.clearTimeout(this.sourceControl.statusTimeout);
        }
        const requestId = this.sourceControl.statusRequestId + 1;
        this.sourceControl.statusRequestId = requestId;
        this.sourceControl.loading = true;
        this.sourceControl.error = "";
        this.sourceControl.statusTimeout = window.setTimeout(() => {
          if (this.sourceControl.statusRequestId !== requestId || !this.sourceControl.loading) {
            return;
          }
          this.sourceControl.loading = false;
          this.sourceControl.error = "Source Control did not respond within 20 seconds. Refresh to retry.";
          this.sourceControl.status = this.sourceControl.error;
          this.sourceControl.statusTimeout = null;
        }, 20_000);
        this.socket.emit("source_control_status", {
          project_path: this.activeProjectPath,
          request_id: requestId,
        });
      },

      initializeRepository() {
        if (!this.socket) {
          return;
        }
        this.sourceControl.operationLoading = true;
        this.socket.emit("source_control_action", {
          action: "initialize",
          project_path: this.activeProjectPath,
        });
      },

      switchSourceBranch() {
        const branch = this.sourceControl.selectedBranch || "";
        if (!branch || !this.socket) {
          return;
        }
        this.sourceControl.operationLoading = true;
        this.socket.emit("source_control_action", {
          action: "switch_branch",
          branch,
          project_path: this.activeProjectPath,
        });
      },

      loadSourceHistory() {
        if (!this.socket || !this.sourceControl.isRepo) {
          return;
        }
        this.socket.emit("source_control_history", {
          project_path: this.activeProjectPath,
          limit: 25,
        });
      },

      syncSourceRemote(action) {
        if (!this.socket || !this.sourceControl.remoteName) {
          this.sourceControl.error = "Configure a Git remote before syncing.";
          return;
        }
        this.sourceControl.operationLoading = true;
        this.socket.emit("source_control_action", {
          action,
          remote: this.sourceControl.remoteName,
          branch: this.sourceControl.remoteBranch,
          project_path: this.activeProjectPath,
        });
      },

      viewSourceDiff(change) {
        if (!change || !this.socket) {
          return;
        }
        this.sourceControl.error = "";
        this.sourceControl.diffPath = change.path;
        this.sourceControl.diff = "Loading diff...";
        this.sourceControl.diffLines = [];
        this.socket.emit("source_control_diff", {
          path: change.path,
          staged: change.staged,
          project_path: this.activeProjectPath,
        });
      },

      stageSourceChange(change) {
        if (!change || !this.socket) {
          return;
        }
        this.sourceControl.operationLoading = true;
        this.socket.emit("source_control_action", {
          action: change.staged ? "unstage" : "stage",
          path: change.path,
          project_path: this.activeProjectPath,
        });
      },

      commitSourceChanges() {
        const message = this.sourceControl.commitMessage.trim();
        if (!message || !this.socket) {
          this.sourceControl.error = "Enter a commit message first.";
          return;
        }
        this.sourceControl.operationLoading = true;
        this.socket.emit("source_control_action", {
          action: "commit",
          message,
          project_path: this.activeProjectPath,
        });
        this.sourceControl.commitMessage = "";
      },

      runActiveFile(requestedFilePath = "") {
        if (this.runInProgress) {
          this.showNotice("A program is already running. Enter input in the terminal first.");
          return;
        }
        const sessionId = this.$store.cm.terminalSessionId;
        const activeFilePath = requestedFilePath || window.cmEditor.filePath;
        if (!activeFilePath) {
          this.$store.cm.activity = "No active file";
          this.showNotice("Open a file before running it.");
          return;
        }
        let filePath = normalizeWorkspaceRelativePath(activeFilePath);
        if (!filePath) {
          this.$store.cm.activity = "No active file";
          this.showNotice("Open a file before running it.");
          return;
        }
        const activeProjectPath = normalizeWorkspaceRelativePath(this.activeProjectPath);
        if (activeProjectPath && filePath !== activeProjectPath && !filePath.startsWith(`${activeProjectPath}/`)) {
          filePath = `${activeProjectPath}/${filePath}`;
        }
        if (!sessionId || !this.socket) {
          if (this.socket) {
            this.pendingRunFile = filePath;
            if (!this.terminalOpening) {
              this.terminalOpening = true;
              this.$store.cm.activity = "Opening terminal...";
              this.socket.emit("terminal_open", {});
            } else {
              this.$store.cm.activity = "Waiting for terminal...";
            }
          } else {
            this.$store.cm.activity = "Terminal is not ready";
          }
          return;
        }
        const normalized = filePath.replaceAll("/", "\\");
        const extension = normalized.split(".").pop().toLowerCase();
        const command = extension === "js" || extension === "ts" ? "node" : "python";
        const runToken = "CM_RUN_COMPLETE_" + Date.now() + "_" + Math.random().toString(16).slice(2);
        const workspaceRoot = String(this.sessionContext.workspaceRoot || "workspace")
          .replaceAll("\\", "/")
          .replace(/\/$/, "");
        const absolutePath = `${workspaceRoot}/${filePath}`.replaceAll("/", "\\");
        const executionPath = `"${absolutePath}"`;
        this.addTerminalLine("input", `$ ${command} ${executionPath}\n`);
        this.runInProgress = true;
        this.runToken = runToken;
        this.runOutputBuffer = "";
        this.socket.emit("terminal_input", {
          session_id: sessionId,
          command: `${command} ${executionPath} & echo ${runToken}`,
        });
      },

      async openGeneratedFile(filePath, content = null) {
        const normalized = normalizeWorkspaceRelativePath(filePath);
        const pathParts = normalized.split("/");
        if (pathParts.length > 1) {
          this.activeProjectPath = pathParts.slice(0, -1).join("/");
          this.activeProjectName = this.activeProjectPath.split("/").pop() || "";
        }
        const result = await window.cmEditor.openFile(normalized, content);
        if (!result.success) {
          this.showNotice(`Unable to open generated file: ${result.error}`);
          return result;
        }
        this.$store.cm.activeFile = normalized;
        this.workspaceSelectedPath = normalized;
        this.workspaceSelectedIsDirectory = false;
        void this.refreshWorkspaceTree(this.activeProjectPath);
        return result;
      },

      toggleWorkspaceTree() {
        this.workspaceTreeOpen = !this.workspaceTreeOpen;
        if (this.workspaceTreeOpen) {
          void this.refreshWorkspaceTree();
        }
      },

      closeWorkspaceTree() {
        this.workspaceTreeOpen = false;
      },

      goToWorkspaceRoot() {
        return this.refreshWorkspaceTree();
      },

      goUpWorkspaceTree() {
        const currentPath = normalizeWorkspaceRelativePath(this.workspaceTreePath);
        if (!currentPath) {
          return this.refreshWorkspaceTree();
        }
        const parentPath = currentPath.split("/").slice(0, -1).join("/");
        return this.refreshWorkspaceTree(parentPath);
      },

      async refreshWorkspaceTree(relativePath = "") {
        const bridge = window.pywebview && window.pywebview.api;
        this.workspaceTreeStatus = "Refreshing...";
        const path = normalizeWorkspaceRelativePath(relativePath);
        try {
          let result = null;
          if (bridge && bridge.get_tree) {
            try {
              result = await bridge.get_tree(path);
            } catch (error) {
              console.warn("Workspace bridge tree request failed", error);
            }
          }

          if (!result || !result.success) {
            const response = await fetch(`/api/workspace/tree?path=${encodeURIComponent(path)}`);
            result = await response.json();
          }

          if (!result.success) {
            this.workspaceTreeStatus = result.error || "Unable to load workspace tree.";
            return result;
          }
          this.workspaceTreePath = path;
          this.workspaceTree = result.items || [];
          this.workspaceTreeStatus = `${this.workspaceTree.length} item(s)`;
          return result;
        } catch (error) {
          this.workspaceTreeStatus = `Unable to load workspace tree: ${error}`;
          return { success: false, error: String(error) };
        }
      },

      async openWorkspaceItem(item) {
        if (item.is_dir) {
          this.activeProjectPath = normalizeWorkspaceRelativePath(item.path);
          this.activeProjectName = item.name;
          return this.refreshWorkspaceTree(item.path);
        }
        this.selectWorkspaceItem(item);
        return this.searchWorkspaceSelection();
      },

      selectWorkspaceItem(item) {
        this.workspaceSelectedPath = normalizeWorkspaceRelativePath(item.path);
        this.workspaceSelectedIsDirectory = Boolean(item.is_dir);
        this.workspaceTreeStatus = `Selected ${item.name}`;
      },

      copyWorkspaceSelection() {
        const selectedPath = normalizeWorkspaceRelativePath(this.workspaceSelectedPath);
        if (!selectedPath) {
          this.workspaceTreeStatus = "Select a file or folder to copy.";
          return;
        }
        this.workspaceClipboardPath = selectedPath;
        this.workspaceTreeStatus = "Copied selection. Open a destination folder, then choose Paste.";
      },

      searchWorkspaceSelection() {
        const selectedPath = normalizeWorkspaceRelativePath(this.workspaceSelectedPath);
        if (!selectedPath) {
          this.workspaceTreeStatus = "Select a file or folder to search.";
          return;
        }
        const fileName = selectedPath.split("/").pop();
        this.searchQuery = fileName;
        this.searchPinnedResults = this.workspaceSelectedIsDirectory
          ? []
          : [{
            id: `workspace-file:${selectedPath}`,
            text: `Workspace file: ${selectedPath}`,
            metadata: { file_path: selectedPath, start_line: 1 },
            match_type: "workspace",
          }];
        this.searchResults = [...this.searchPinnedResults];
        this.workspaceTreeOpen = false;
        this.searchOpen = true;
        this.searchStatus = this.searchPinnedResults.length
          ? `Selected ${fileName}. Click the result to open it.`
          : `Searching for ${fileName}...`;
        this.$nextTick(() => {
          this.$refs.searchInput && this.$refs.searchInput.focus();
          this.searchCodebase({ preservePinned: true });
        });
      },

      async pasteWorkspaceSelection() {
        const bridge = window.pywebview && window.pywebview.api;
        const sourcePath = normalizeWorkspaceRelativePath(this.workspaceClipboardPath);
        const destinationPath = normalizeWorkspaceRelativePath(this.workspaceTreePath);
        if (!sourcePath) {
          this.workspaceTreeStatus = "Copy a file or folder before pasting.";
          return { success: false, error: this.workspaceTreeStatus };
        }
        if (!bridge || !bridge.copy_workspace_item) {
          this.workspaceTreeStatus = "Workspace paste requires the desktop bridge.";
          return { success: false, error: this.workspaceTreeStatus };
        }

        this.workspaceTreeStatus = "Pasting...";
        try {
          const result = await bridge.copy_workspace_item(sourcePath, destinationPath);
          if (!result || !result.success) {
            this.workspaceTreeStatus = (result && result.error) || "Unable to paste workspace item.";
            return result || { success: false, error: this.workspaceTreeStatus };
          }
          this.workspaceSelectedPath = normalizeWorkspaceRelativePath(result.path);
          this.workspaceSelectedIsDirectory = Boolean(result.is_dir);
          await this.refreshWorkspaceTree(destinationPath);
          this.workspaceTreeStatus = `Pasted ${result.path}`;
          return result;
        } catch (error) {
          this.workspaceTreeStatus = `Unable to paste workspace item: ${error}`;
          return { success: false, error: String(error) };
        }
      },

      toggleSearchPanel() {
        this.searchOpen = !this.searchOpen;
        if (this.searchOpen) {
          this.$nextTick(() => this.$refs.searchInput && this.$refs.searchInput.focus());
        }
      },

      searchCodebase({ preservePinned = false } = {}) {
        const query = this.searchQuery.trim();
        if (!preservePinned) {
          this.searchPinnedResults = [];
        }
        if (!query) {
          this.searchResults = [...this.searchPinnedResults];
          this.searchStatus = "Enter a search query.";
          return;
        }
        if (!this.socket) {
          this.searchResults = [...this.searchPinnedResults];
          this.searchStatus = this.searchPinnedResults.length
            ? "Selected workspace file is ready to open."
            : "Backend is not connected.";
          return;
        }
        this.searchStatus = "Searching indexed workspace...";
        this.socket.emit("codebase_search", { query, file_types: this.allFileTypes ? [] : this.indexFileTypes });
      },

      reindexWorkspace() {
        if (!this.socket || this.$store.cm.indexingActive) {
          if (!this.socket) {
            this.showNotice("Backend is not connected.");
          }
          return;
        }
        this.$store.cm.indexingActive = true;
        this.$store.cm.indexingStatus = "Starting reindex...";
        this.$store.cm.indexingErrors = [];
        this.beginWork("Starting workspace reindex", 5, "indexing");
        this.socket.emit("workspace_reindex", {
          file_types: this.allFileTypes ? [] : this.indexFileTypes,
          incremental: true,
        });
        this.showNotice(this.allFileTypes || !this.indexFileTypes.length
          ? "Reindexing all workspace file types..."
          : `Reindexing ${this.indexFileTypes.join(", ")} files...`);
      },

      async openSearchResult(result) {
        const filePath = result && result.metadata && result.metadata.file_path;
        if (filePath) {
          const openResult = await this.openGeneratedFile(filePath);
          if (openResult && openResult.success) {
            this.searchPinnedResults = [];
            this.searchOpen = false;
          }
        }
      },

      connectDatabase() {
        this.dbStatus = "Connecting...";
        this.dbStatusError = false;
        this.socket.emit("db_connect", {
          connection_id: this.dbForm.connectionId,
          db_type: this.dbForm.dbType,
          connection_string: this.dbForm.connectionString,
        });
      },

      selectDatabase(connectionId) {
        this.$store.cm.activeDbConnection = connectionId;
        this.$store.cm.dbResults = null;
        this.socket.emit("db_list_tables", { connection_id: connectionId });
      },

      setSql(query) {
        window.cmSqlEditor.setValue(query);
      },

      runQuery() {
        const connectionId = this.$store.cm.activeDbConnection;
        if (!window.cmSqlEditor.editor) {
          window.cmSqlEditor.init();
          this.dbStatus = "SQL editor is still loading. Please wait a moment and try again.";
          this.dbStatusError = true;
          return;
        }
        const sqlQuery = window.cmSqlEditor.getValue();
        if (!connectionId || !sqlQuery.trim()) {
          this.dbStatus = "Connect to a database and enter a query first.";
          this.dbStatusError = true;
          return;
        }
        this.dbStatus = "Running query...";
        this.dbStatusError = false;
        this.socket.emit("db_execute_query", { connection_id: connectionId, sql_query: sqlQuery });
      },

      addTerminalLine(type, data) {
        const lines = this.$store.cm.terminalLines;
        const lastLine = lines[lines.length - 1];
        if (lastLine && lastLine.type === type && !String(lastLine.data).endsWith("\n")) {
          lastLine.data += data;
        } else {
          lines.push({ type, data });
        }
        if (this.$store.cm.terminalLines.length > 1000) {
          this.$store.cm.terminalLines.splice(0, this.$store.cm.terminalLines.length - 1000);
        }
        this.$nextTick(() => {
          const output = this.$refs.terminalOutput;
          if (output) {
            output.scrollTop = output.scrollHeight;
          }
        });
      },

      sendTerminalCommand() {
        const command = this.terminalInput;
        const sessionId = this.$store.cm.terminalSessionId;
        if (!command.trim() || !sessionId || !this.socket) {
          return;
        }
        this.addTerminalLine("input", `$ ${command}\n`);
        this.socket.emit("terminal_input", { session_id: sessionId, command });
        this.terminalInput = "";
      },

      closeTerminal() {
        const sessionId = this.$store.cm.terminalSessionId;
        if (sessionId && this.socket) {
          this.socket.emit("terminal_close", { session_id: sessionId });
        }
      },

      clearAgentTrace() {
        this.$store.cm.agentTrace = [];
      },

      refreshAgentPerformance() {
        if (this.socket) {
          this.socket.emit("agent_performance_history", { limit: 25 });
        }
      },

      resolveDiffReview(accepted) {
        if (!this.diffReview || !this.socket) {
          return;
        }
        this.socket.emit("diff_review_action", {
          review_id: this.diffReview.review_id,
          accepted: Boolean(accepted),
        });
      },

      resolveApproval(approved) {
        if (!this.approvalRequest || !this.socket) {
          return;
        }
        if (approved && this.approvalRequest.level === "elevated" && this.approvalPhrase.trim().toUpperCase() !== "APPROVE") {
          this.showNotice("Type APPROVE to authorize this elevated action.");
          return;
        }
        this.socket.emit("approval_action", {
          approval_id: this.approvalRequest.approval_id,
          approved: Boolean(approved),
          confirmation_text: this.approvalPhrase,
        });
      },

      cancelRequest() {
        if (!this.requestActive || !this.socket) {
          return;
        }
        this.socket.emit("agent_cancel", { request_id: this.requestId });
      },

      retryLastRequest() {
        if (!this.lastRequest || this.requestActive || !this.socket) {
          return;
        }
        this.dispatchAgentRequest({ ...this.lastRequest }, false);
      },

      sendMessage() {
        const content = this.draft.trim();
        if (!content || !this.socket || this.requestActive) {
          return;
        }

        this.messages.push({ role: "user", content });
        this.lastRequest = {
          message: content,
          skill_ids: [...this.selectedSkills],
          tool_ids: [...this.selectedTools],
          auto_capabilities: this.autoCapabilities,
          max_handoffs: this.handoffLimit,
          active_project_path: this.activeProjectPath,
        };
        this.dispatchAgentRequest({ ...this.lastRequest }, false);
        this.draft = "";
        this.skillsOpen = false;
        this.toolsOpen = false;
        void this.saveSession({ silent: true });
      },

      dispatchAgentRequest(payload, addUserMessage = false) {
        if (!this.socket || this.requestActive) {
          return;
        }
        if (addUserMessage && payload.message) {
          this.messages.push({ role: "user", content: payload.message });
        }
        this.requestId = createSessionId();
        this.requestActive = true;
        this.streamingMessageIndex = null;
        this.capabilityRecommendation = null;
        this.beginWork("Preparing request", 8, "agent");
        this.clearAgentTrace();
        this.$store.cm.agentState = null;
        this.$store.cm.agentMetrics = {
          model: this.sessionContext.model || "",
          prompt_tokens: 0,
          completion_tokens: 0,
          total_tokens: 0,
          cached_prompt_tokens: 0,
          prompt_cache_enabled: true,
          execution_time_seconds: 0,
          agent_trace: [],
        };
        this.socket.emit("agent_message", { ...payload, request_id: this.requestId });
      },
    };
  };
})();
