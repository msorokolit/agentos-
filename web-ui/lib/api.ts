// Lightweight typed client for the api-gateway.
// We use cookies for auth (set by /auth/oidc/callback), so all requests must
// include credentials.

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

export interface Workspace {
  id: string;
  tenant_id: string;
  name: string;
  slug: string;
  created_at: string;
}

export interface Membership {
  workspace_id: string;
  workspace_slug: string;
  workspace_name: string;
  role: "owner" | "admin" | "builder" | "member" | "viewer";
}

export interface Me {
  user_id: string;
  tenant_id: string;
  email: string;
  display_name: string | null;
  is_superuser: boolean;
  workspaces: Membership[];
}

export interface Member {
  user_id: string;
  email: string;
  display_name: string | null;
  role: Membership["role"];
  added_at: string;
}

export type ModelProvider = "ollama" | "vllm" | "openai_compat";
export type ModelKind = "chat" | "embedding";

export interface Model {
  id: string;
  alias: string;
  provider: ModelProvider;
  endpoint: string;
  model_name: string;
  kind: ModelKind;
  capabilities: Record<string, unknown>;
  default_params: Record<string, unknown>;
  enabled: boolean;
}

export interface ModelTestResult {
  ok: boolean;
  latency_ms: number;
  detail: string | null;
}

export interface DocumentRow {
  id: string;
  workspace_id: string;
  collection_id: string | null;
  title: string;
  mime: string | null;
  sha256: string | null;
  size_bytes: number;
  status: "pending" | "parsing" | "embedding" | "ready" | "failed";
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

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData =
    typeof FormData !== "undefined" && init?.body instanceof FormData;
  const baseHeaders: Record<string, string> = {};
  if (!isFormData) {
    baseHeaders["Content-Type"] = "application/json";
  }
  const { headers: extraHeaders, ...rest } = init ?? {};
  const headers = {
    ...baseHeaders,
    ...((extraHeaders as Record<string, string>) ?? {}),
  };
  const res = await fetch(`${API_URL}${path}`, {
    credentials: "include",
    headers,
    ...rest,
  });
  if (res.status === 401) {
    throw new HttpError(401, "unauthorized");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? body.title ?? detail;
    } catch {
      /* swallow */
    }
    throw new HttpError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export class HttpError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
  }
}

export const api = {
  loginUrl(returnTo?: string): string {
    const u = new URL(`${API_URL}/api/v1/auth/oidc/login`);
    if (returnTo) u.searchParams.set("return_to", returnTo);
    return u.toString();
  },
  async logout(): Promise<void> {
    await http<void>("/api/v1/auth/logout", { method: "POST" });
  },
  me(): Promise<Me> {
    return http<Me>("/api/v1/me");
  },
  listWorkspaces(): Promise<Workspace[]> {
    return http<Workspace[]>("/api/v1/workspaces");
  },
  createWorkspace(body: { name: string; slug: string }): Promise<Workspace> {
    return http<Workspace>("/api/v1/workspaces", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  listMembers(workspaceId: string): Promise<Member[]> {
    return http<Member[]>(`/api/v1/workspaces/${workspaceId}/members`);
  },
  addMember(
    workspaceId: string,
    body: { email: string; role: Member["role"] },
  ): Promise<Member> {
    return http<Member>(`/api/v1/workspaces/${workspaceId}/members`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  updateMember(
    workspaceId: string,
    userId: string,
    body: { role: Member["role"] },
  ): Promise<Member> {
    return http<Member>(`/api/v1/workspaces/${workspaceId}/members/${userId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  },
  removeMember(workspaceId: string, userId: string): Promise<void> {
    return http<void>(`/api/v1/workspaces/${workspaceId}/members/${userId}`, {
      method: "DELETE",
    });
  },
  // ----- Models admin -----
  listModels(): Promise<Model[]> {
    return http<Model[]>("/api/v1/admin/models");
  },
  createModel(body: {
    alias: string;
    provider: ModelProvider;
    endpoint: string;
    model_name: string;
    kind: ModelKind;
  }): Promise<Model> {
    return http<Model>("/api/v1/admin/models", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  updateModel(id: string, body: Partial<Pick<Model, "endpoint" | "model_name" | "enabled">>): Promise<Model> {
    return http<Model>(`/api/v1/admin/models/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  },
  deleteModel(id: string): Promise<void> {
    return http<void>(`/api/v1/admin/models/${id}`, { method: "DELETE" });
  },
  testModel(id: string): Promise<ModelTestResult> {
    return http<ModelTestResult>(`/api/v1/admin/models/${id}/test`, {
      method: "POST",
    });
  },
  // ----- Knowledge -----
  listDocuments(workspaceId: string): Promise<DocumentRow[]> {
    return http<DocumentRow[]>(`/api/v1/workspaces/${workspaceId}/documents`);
  },
  uploadDocument(
    workspaceId: string,
    file: File,
    opts: { collection_id?: string; title?: string; embed_alias?: string } = {},
  ): Promise<DocumentRow> {
    const fd = new FormData();
    fd.append("file", file);
    if (opts.collection_id) fd.append("collection_id", opts.collection_id);
    if (opts.title) fd.append("title", opts.title);
    if (opts.embed_alias) fd.append("embed_alias", opts.embed_alias);
    return http<DocumentRow>(
      `/api/v1/workspaces/${workspaceId}/documents`,
      {
        method: "POST",
        body: fd,
        // override Content-Type so the browser sets the multipart boundary.
        headers: {},
      },
    );
  },
  deleteDocument(workspaceId: string, documentId: string): Promise<void> {
    return http<void>(
      `/api/v1/workspaces/${workspaceId}/documents/${documentId}`,
      { method: "DELETE" },
    );
  },
  search(
    workspaceId: string,
    query: string,
    top_k = 8,
  ): Promise<SearchResponse> {
    return http<SearchResponse>(`/api/v1/workspaces/${workspaceId}/search`, {
      method: "POST",
      body: JSON.stringify({ query, top_k }),
    });
  },
};
