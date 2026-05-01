import { describe, expect, it, vi } from "vitest";
import { AgenticOSAPIError, AgenticOSClient } from "../src/index";

const BASE = "http://api.test";

function makeFetchMock(
  routes: { method: string; pattern: RegExp; respond: (req: Request) => Response | Promise<Response> }[],
) {
  return vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const req = new Request(input as RequestInfo, init);
    for (const r of routes) {
      if (req.method.toUpperCase() === r.method && r.pattern.test(req.url)) {
        return r.respond(req);
      }
    }
    return new Response(`no mock: ${req.method} ${req.url}`, { status: 599 });
  });
}

describe("AgenticOSClient", () => {
  it("sends Bearer token and parses JSON", async () => {
    let seen: Headers | undefined;
    const fetchImpl = makeFetchMock([
      {
        method: "GET",
        pattern: /\/api\/v1\/me$/,
        respond: (req) => {
          seen = req.headers;
          return new Response(
            JSON.stringify({
              user_id: "u",
              tenant_id: "t",
              email: "x@y",
              display_name: null,
              is_superuser: false,
              workspaces: [],
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        },
      },
    ]);

    const c = new AgenticOSClient({ baseUrl: BASE, token: "aos_t", fetch: fetchImpl });
    const me = await c.me();
    expect(me.email).toBe("x@y");
    expect(seen?.get("authorization")).toBe("Bearer aos_t");
  });

  it("maps problem+json into AgenticOSAPIError", async () => {
    const fetchImpl = makeFetchMock([
      {
        method: "GET",
        pattern: /\/api\/v1\/me$/,
        respond: () =>
          new Response(
            JSON.stringify({
              type: "about:blank",
              title: "Forbidden",
              status: 403,
              code: "forbidden",
              detail: "no role",
            }),
            { status: 403, headers: { "content-type": "application/problem+json" } },
          ),
      },
    ]);
    const c = new AgenticOSClient({ baseUrl: BASE, token: "x", fetch: fetchImpl });
    await expect(c.me()).rejects.toMatchObject({
      status: 403,
      code: "forbidden",
      title: "Forbidden",
      detail: "no role",
    });
    await expect(c.me()).rejects.toBeInstanceOf(AgenticOSAPIError);
  });

  it("create workspace returns the typed payload", async () => {
    const ws = {
      id: "w1",
      tenant_id: "t1",
      name: "Demo",
      slug: "demo",
      created_at: "2026-04-30T00:00:00Z",
    };
    let bodySeen: string | undefined;
    const fetchImpl = makeFetchMock([
      {
        method: "POST",
        pattern: /\/api\/v1\/workspaces$/,
        respond: async (req) => {
          bodySeen = await req.text();
          return new Response(JSON.stringify(ws), {
            status: 201,
            headers: { "content-type": "application/json" },
          });
        },
      },
    ]);
    const c = new AgenticOSClient({ baseUrl: BASE, fetch: fetchImpl });
    const out = await c.createWorkspace({ name: "Demo", slug: "demo" });
    expect(out.slug).toBe("demo");
    expect(JSON.parse(bodySeen!)).toEqual({ name: "Demo", slug: "demo" });
  });

  it("top-level run + session + collectionSearch URLs", async () => {
    const calls: string[] = [];
    const fetchImpl = makeFetchMock([
      {
        method: "POST",
        pattern: /\/api\/v1\/sessions$/,
        respond: (req) => {
          calls.push(req.url);
          return new Response(
            JSON.stringify({
              id: "s1",
              agent_id: "a1",
              workspace_id: "w1",
              title: null,
              created_at: "2026-04-30T00:00:00Z",
            }),
            { status: 201, headers: { "content-type": "application/json" } },
          );
        },
      },
      {
        method: "POST",
        pattern: /\/api\/v1\/agents\/a1\/run$/,
        respond: (req) => {
          calls.push(req.url);
          return new Response(
            JSON.stringify({
              final_message: "hi",
              tool_calls: [],
              tool_results: [],
              citations: [],
              iterations: 1,
              tokens_in: 1,
              tokens_out: 1,
              error: null,
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        },
      },
      {
        method: "POST",
        pattern: /\/api\/v1\/collections\/c1\/search$/,
        respond: (req) => {
          calls.push(req.url);
          return new Response(
            JSON.stringify({ query: "hi", hits: [] }),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        },
      },
    ]);
    const c = new AgenticOSClient({ baseUrl: BASE, fetch: fetchImpl });
    await c.session("a1");
    await c.run("a1", { user_message: "hi" });
    await c.collectionSearch("c1", "hi");
    expect(calls).toEqual([
      `${BASE}/api/v1/sessions`,
      `${BASE}/api/v1/agents/a1/run`,
      `${BASE}/api/v1/collections/c1/search`,
    ]);
  });

  it("204 returns undefined without choking on empty body", async () => {
    const fetchImpl = makeFetchMock([
      {
        method: "DELETE",
        pattern: /\/api\/v1\/agents\/a1$/,
        respond: () => new Response(null, { status: 204 }),
      },
    ]);
    const c = new AgenticOSClient({ baseUrl: BASE, fetch: fetchImpl });
    await expect(c.deleteAgent("a1")).resolves.toBeUndefined();
  });

  it("chatWebSocketUrl swaps scheme + appends token", () => {
    const c = new AgenticOSClient({ baseUrl: BASE, token: "aos_t" });
    const url = c.chatWebSocketUrl("a1", "s1");
    expect(url).toBe("ws://api.test/api/v1/chat/a1/ws?session_id=s1&token=aos_t");
  });
});
