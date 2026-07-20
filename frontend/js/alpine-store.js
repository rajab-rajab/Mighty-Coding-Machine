document.addEventListener("alpine:init", () => {
  Alpine.store("editor", {
    openFiles: [],
    dirtyFiles: [],
  });

  Alpine.store("ui", {
    showPalette: false,
    showTerminal: true,
  });

  Alpine.store("cm", {
    connected: false,
    activity: "Ready",
    activeFile: "main.py",
    codePresentation: null,
    terminalLines: [{ type: "system", data: "Terminal ready.\n" }],
    terminalSessionId: null,
    terminalConnected: false,
    agentTrace: [],
    agentPlan: null,
    agentState: null,
    agentPerformance: { agents: [], history: [] },
    showAgentTrace: true,
    agentMetrics: {
      model: "",
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
      cached_prompt_tokens: 0,
      prompt_cache_enabled: true,
      execution_time_seconds: 0,
      agent_trace: [],
    },
    dbConnections: [],
    activeDbConnection: null,
    dbTables: [],
    dbResults: null,
    indexingStatus: "Waiting for indexer...",
    indexingActive: false,
    indexingProgress: { current: 0, total: 0, indexed: 0, skipped: 0, errors: 0 },
    indexingErrors: [],
    workingActive: false,
    workingName: "Ready",
    workingProgress: 0,
    workingSource: "",
  });
});
