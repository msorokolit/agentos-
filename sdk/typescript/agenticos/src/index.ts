/**
 * @agenticos/sdk — typed client for the AgenticOS API gateway.
 *
 * Authentication: pass either a session cookie (browser) or a workspace
 * API key (`aos_…`) via the `token` option. The latter goes out as
 * `Authorization: Bearer …`.
 *
 * Errors are surfaced as `AgenticOSAPIError` carrying the RFC-7807
 * `problem+json` fields.
 */

export class AgenticOSAPIError extends Error {
  constructor(
    public readonly status: number,
    public readonly title: string | null,
    public readonly code: string | null,
    public readonly detail: string | null,
    public readonly body: unknown,
  ) {
    super(detail ?? title ?? `HTTP ${status}`);
  }
}

export interface ClientOptions {
  baseUrl: string;
  token?: string;
  fetch?: typeof fetch;
  /** Sent as `User-Agent` on every request. */
  userAgent?: string;
  /** Browser sessions need this so cookies travel; SDK callers in Node
   *  can leave it `omit` (the default). */
  credentials?: RequestCredentials;
}

export type WorkspaceRole = "owner" | "admin" | "builder" | "member" | "viewer";
export type ToolKind = "builtin" | "http" | "openapi" | "mcp";
export type DocumentStatus =
  | "pending"
  | "parsing"
  | "embedding"
  | "ready"
  | "failed";
export type MessageRole = "system" | "user" | "assistant" | "tool";

export interface Workspace {
  id: string;
  tenant_id: string;
  name: string;
  slug: string;
  created_at: string;
}

export interface Member {
  user_id: string;
  email: string;
  display_name: string | null;
  role: WorkspaceRole;
  added_at: string;
}

export interface Tool {
  id: string;
  workspace_id: string | null;
  name: string;
  display_name: string | null;
  description: string | null;
  kind: ToolKind;
  descriptor: Record<string, unknown>;
  scopes: string[];
  enabled: boolean;
  created_at: string;
}

export interface DocumentRow {
  id: string;
  workspace_id: string;
  collection_id: string | null;
  title: string;
  mime: string | null;
  sha256: string | null;
  size_bytes: number;
  status: DocumentStatus;
  error: string | null;
  chunk_count: number;
  meta: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface SearchHit {
  chunk_id: string;
  document_id: string;
  document_title: string;
  ord: number;
  text: string;
  score: number;
  meta: Record<string, unknown>;
}

export interface SearchResponse {
  query: string;
  hits: SearchHit[];
}

export interface AgentRow {
  id: string;
  workspace_id: string;
  name: string;
  slug: string;
  description: string | null;
  system_prompt: string;
  model_alias: string;
  graph_kind: string;
  config: Record<string, unknown>;
  tool_ids: string[];
  rag_collection_id: string | null;
  version: number;
  enabled: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface SessionRow {
  id: string;
  agent_id: string;
  workspace_id: string;
  title: string | null;
  created_at: string;
}

export interface MessageRow {
  id: string;
  role: MessageRole;
  content: string | null;
  tool_call: Record<string, unknown> | null;
  citations: Record<string, unknown>[];
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
  created_at: string;
}

export interface ToolCall {
  id?: string;
  name: string;
  args: Record<string, unknown>;
}

export interface ToolResult {
  id?: string;
  name: string;
  ok: boolean;
  result?: unknown;
  error?: string | null;
}

export interface RunResult {
  final_message: string;
  tool_calls: ToolCall[];
  tool_results: ToolResult[];
  citations: Record<string, unknown>[];
  iterations: number;
  tokens_in: number;
  tokens_out: number;
  error: string | null;
  session_id?: string;
}

export interface MeResponse {
  user_id: string;
  tenant_id: string;
  email: string;
  display_name: string | null;
  is_superuser: boolean;
  workspaces: {
    workspace_id: string;
    workspace_slug: string;
    workspace_name: string;
    role: WorkspaceRole;
  }[];
}

export class AgenticOSClient {
  private readonly base: string;
  private readonly token?: string;
  private readonly fetchImpl: typeof fetch;
  private readonly userAgent: string;
  private readonly credentials: RequestCredentials;

  constructor(options: ClientOptions) {
    if (!options.baseUrl) throw new TypeError("baseUrl is required");
    this.base = options.baseUrl.replace(/\/+$/, "");
    this.token = options.token;
    this.fetchImpl =
      options.fetch ??
      (typeof fetch !== "undefined" ? fetch.bind(globalThis) : (undefined as never));
    this.userAgent = options.userAgent ?? "agenticos-ts-sdk/0.1.0";
    this.credentials = options.credentials ?? "omit";
    if (!this.fetchImpl) {
      throw new Error(
        "no fetch implementation available; pass options.fetch or upgrade to Node 18+",
      );
    }
  }

  private headers(extra?: HeadersInit): Headers {
    const h = new Headers(extra);
    h.set("Accept", "application/json");
    if (!h.has("User-Agent")) h.set("User-Agent", this.userAgent);
    if (this.token && !h.has("Authorization")) {
      h.set("Authorization", `Bearer ${this.token}`);
    }
    return h;
  }

  private async request<T>(
    method: string,
    path: string,
    init?: { body?: unknown; headers?: HeadersInit; query?: Record<string, string | number | undefined> },
  ): Promise<T> {
    const url = new URL(`${this.base}${path}`);
    for (const [k, v] of Object.entries(init?.query ?? {})) {
      if (v === undefined || v === null) continue;
      url.searchParams.set(k, String(v));
    }

    const isFormData =
      typeof FormData !== "undefined" && init?.body instanceof FormData;
    const headers = this.headers(init?.headers);
    let body: BodyInit | undefined;
    if (init?.body !== undefined && init.body !== null) {
      if (isFormData) {
        body = init.body as BodyInit;
        // Let fetch set the multipart boundary.
        headers.delete("Content-Type");
      } else if (typeof init.body === "string" || init.body instanceof Uint8Array) {
        body = init.body as BodyInit;
      } else {
        body = JSON.stringify(init.body);
        if (!headers.has("Content-Type"))
          headers.set("Content-Type", "application/json");
      }
    }

    const resp = await this.fetchImpl(url.toString(), {
      method,
      body,
      headers,
      credentials: this.credentials,
    });

    if (resp.status === 204) {
      return undefined as T;
    }

    const text = await resp.text();
    let parsed: unknown = undefined;
    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = text;
      }
    }

    if (!resp.ok) {
      const p = (parsed ?? {}) as Record<string, unknown>;
      throw new AgenticOSAPIError(
        resp.status,
        (p.title as string) ?? null,
        (p.code as string) ?? null,
        (p.detail as string) ?? null,
        parsed,
      );
    }
    return parsed as T;
  }

  // -------------------------------------------------------------------
  // Health + auth
  // -------------------------------------------------------------------
  health(): Promise<{ status: string; service: string }> {
    return this.request("GET", "/healthz");
  }

  me(): Promise<MeResponse> {
    return this.request("GET", "/api/v1/me");
  }

  refresh(): Promise<{ refreshed: boolean }> {
    return this.request("POST", "/api/v1/auth/token/refresh");
  }

  logout(): Promise<void> {
    return this.request<void>("POST", "/api/v1/auth/logout");
  }

  // -------------------------------------------------------------------
  // Workspaces
  // -------------------------------------------------------------------
  listWorkspaces(): Promise<Workspace[]> {
    return this.request("GET", "/api/v1/workspaces");
  }

  createWorkspace(body: { name: string; slug: string }): Promise<Workspace> {
    return this.request("POST", "/api/v1/workspaces", { body });
  }

  listMembers(workspaceId: string): Promise<Member[]> {
    return this.request("GET", `/api/v1/workspaces/${workspaceId}/members`);
  }

  // -------------------------------------------------------------------
  // Tools
  // -------------------------------------------------------------------
  listBuiltins(): Promise<{ name: string; description: string; parameters: Record<string, unknown> }[]> {
    return this.request("GET", "/api/v1/builtins");
  }

  listTools(workspaceId: string): Promise<Tool[]> {
    return this.request("GET", `/api/v1/workspaces/${workspaceId}/tools`);
  }

  createTool(
    workspaceId: string,
    body: {
      name: string;
      kind: ToolKind;
      descriptor: Record<string, unknown>;
      scopes?: string[];
    },
  ): Promise<Tool> {
    return this.request("POST", `/api/v1/workspaces/${workspaceId}/tools`, { body });
  }

  invokeTool(
    workspaceId: string,
    toolId: string,
    args: Record<string, unknown>,
  ): Promise<{ ok: boolean; result?: unknown; error?: string | null; latency_ms?: number }> {
    return this.request(
      "POST",
      `/api/v1/workspaces/${workspaceId}/tools/${toolId}/invoke`,
      { body: { args } },
    );
  }

  // -------------------------------------------------------------------
  // Knowledge
  // -------------------------------------------------------------------
  uploadDocument(
    workspaceId: string,
    file: Blob,
    opts: {
      filename?: string;
      collection_id?: string;
      title?: string;
      embed_alias?: string;
      async_ingest?: boolean;
    } = {},
  ): Promise<DocumentRow> {
    const fd = new FormData();
    fd.append("file", file, opts.filename ?? "upload");
    if (opts.collection_id) fd.append("collection_id", opts.collection_id);
    if (opts.title) fd.append("title", opts.title);
    if (opts.embed_alias) fd.append("embed_alias", opts.embed_alias);
    return this.request("POST", `/api/v1/workspaces/${workspaceId}/documents`, {
      body: fd,
      query: opts.async_ingest ? { async_ingest: "true" } : undefined,
    });
  }

  listDocuments(workspaceId: string): Promise<DocumentRow[]> {
    return this.request("GET", `/api/v1/workspaces/${workspaceId}/documents`);
  }

  /** Top-level by-id document fetch (PLAN §4 ``GET /documents/{id}``). */
  getDocument(documentId: string): Promise<DocumentRow> {
    return this.request("GET", `/api/v1/documents/${documentId}`);
  }

  getDocumentStatus(workspaceId: string, documentId: string): Promise<{
    id: string;
    status: DocumentStatus;
    chunk_count: number;
    error: string | null;
    updated_at: string | null;
  }> {
    return this.request(
      "GET",
      `/api/v1/workspaces/${workspaceId}/documents/${documentId}/status`,
    );
  }

  search(
    workspaceId: string,
    query: string,
    opts: { top_k?: number; collection_id?: string } = {},
  ): Promise<SearchResponse> {
    if (opts.collection_id) {
      return this.request(
        "POST",
        `/api/v1/workspaces/${workspaceId}/collections/${opts.collection_id}/search`,
        { body: { query, top_k: opts.top_k ?? 8 } },
      );
    }
    return this.request("POST", `/api/v1/workspaces/${workspaceId}/search`, {
      body: { query, top_k: opts.top_k ?? 8 },
    });
  }

  /** Top-level collection search (PLAN §4 ``POST /collections/{id}/search``). */
  collectionSearch(
    collectionId: string,
    query: string,
    opts: { top_k?: number } = {},
  ): Promise<SearchResponse> {
    return this.request(
      "POST",
      `/api/v1/collections/${collectionId}/search`,
      { body: { query, top_k: opts.top_k ?? 8 } },
    );
  }

  // -------------------------------------------------------------------
  // Agents
  // -------------------------------------------------------------------
  listAgents(workspaceId: string): Promise<AgentRow[]> {
    return this.request("GET", `/api/v1/workspaces/${workspaceId}/agents`);
  }

  createAgent(
    workspaceId: string,
    body: {
      name: string;
      slug: string;
      model_alias: string;
      system_prompt?: string;
      tool_ids?: string[];
      rag_collection_id?: string | null;
      config?: Record<string, unknown>;
    },
  ): Promise<AgentRow> {
    return this.request("POST", `/api/v1/workspaces/${workspaceId}/agents`, { body });
  }

  /** Top-level by-id agent (PLAN §4). */
  getAgent(agentId: string): Promise<AgentRow> {
    return this.request("GET", `/api/v1/agents/${agentId}`);
  }

  patchAgent(agentId: string, body: Partial<AgentRow>): Promise<AgentRow> {
    return this.request("PATCH", `/api/v1/agents/${agentId}`, { body });
  }

  deleteAgent(agentId: string): Promise<void> {
    return this.request<void>("DELETE", `/api/v1/agents/${agentId}`);
  }

  /** Sync run via the top-level route (PLAN §4 ``POST /agents/{id}/run``). */
  run(
    agentId: string,
    body: { user_message: string; session_id?: string },
  ): Promise<RunResult> {
    return this.request("POST", `/api/v1/agents/${agentId}/run`, { body });
  }

  // -------------------------------------------------------------------
  // Sessions
  // -------------------------------------------------------------------
  /** Top-level ``POST /api/v1/sessions {agent_id}``. */
  session(agentId: string, opts: { title?: string } = {}): Promise<SessionRow> {
    return this.request("POST", "/api/v1/sessions", {
      body: { agent_id: agentId, ...opts },
    });
  }

  sessionMessages(sessionId: string): Promise<MessageRow[]> {
    return this.request("GET", `/api/v1/sessions/${sessionId}/messages`);
  }

  endSession(workspaceId: string, sessionId: string): Promise<{
    session_id: string;
    job_id: string | null;
    queued: boolean;
  }> {
    return this.request(
      "POST",
      `/api/v1/workspaces/${workspaceId}/sessions/${sessionId}/end`,
    );
  }

  // -------------------------------------------------------------------
  // WebSocket helpers
  // -------------------------------------------------------------------
  /** Build the WebSocket URL for streaming chat. */
  chatWebSocketUrl(agentId: string, sessionId?: string): string {
    const u = new URL(
      `${this.base.replace(/^http/, "ws")}/api/v1/chat/${agentId}/ws`,
    );
    if (sessionId) u.searchParams.set("session_id", sessionId);
    if (this.token) u.searchParams.set("token", this.token);
    return u.toString();
  }
}

export default AgenticOSClient;
