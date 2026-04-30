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

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
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
};
