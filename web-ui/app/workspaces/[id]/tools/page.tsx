"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  api,
  type Tool,
  type ToolBuiltinDescriptor,
  type ToolKind,
} from "../../../../lib/api";
import {
  button,
  buttonSecondary,
  card,
  colors,
  input,
  tag,
} from "../../../../lib/styles";

const KINDS: ToolKind[] = ["builtin", "http", "openapi", "mcp"];

export default function ToolsPage() {
  const params = useParams<{ id: string }>();
  const wsId = params.id;

  const [tools, setTools] = useState<Tool[]>([]);
  const [builtins, setBuiltins] = useState<ToolBuiltinDescriptor[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [kind, setKind] = useState<ToolKind>("builtin");
  const [chosenBuiltin, setChosenBuiltin] = useState<string>("");
  const [name, setName] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [scopes, setScopes] = useState("safe");

  // Per-tool invoke state
  const [invokeArgs, setInvokeArgs] = useState<Record<string, string>>({});
  const [invokeResult, setInvokeResult] = useState<Record<string, string>>({});

  async function reload() {
    try {
      const [t, b] = await Promise.all([
        api.listTools(wsId),
        api.listBuiltins(),
      ]);
      setTools(t);
      setBuiltins(b);
      if (!chosenBuiltin && b.length) setChosenBuiltin(b[0].name);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    if (wsId) reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsId]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    try {
      let descriptor: Record<string, unknown> = {};
      let toolName = name;
      if (kind === "builtin") {
        const b = builtins.find((x) => x.name === chosenBuiltin);
        if (!b) {
          setError("pick a built-in");
          return;
        }
        toolName = b.name;
        descriptor = {
          name: b.name,
          description: b.description,
          parameters: b.parameters,
        };
      } else if (kind === "http") {
        descriptor = { endpoint, method: "GET" };
      } else if (kind === "openapi") {
        descriptor = { server_url: endpoint, operation: { path: "/", method: "GET" } };
      } else if (kind === "mcp") {
        descriptor = { endpoint };
      }
      await api.createTool(wsId, {
        name: toolName,
        kind,
        descriptor,
        scopes: scopes.split(",").map((s) => s.trim()).filter(Boolean),
      });
      setName("");
      setEndpoint("");
      await reload();
    } catch (e2) {
      setError(String(e2));
    }
  }

  return (
    <div style={{ maxWidth: 1000, margin: "0 auto", display: "grid", gap: "1.25rem" }}>
      <Link href="/workspaces" style={{ color: colors.muted, fontSize: 14 }}>
        ← Workspaces
      </Link>
      <h1 style={{ margin: 0 }}>Tools</h1>
      <p style={{ color: colors.muted, marginTop: 0 }}>
        Register tools agents can call. Built-ins are shipped with AgenticOS;
        HTTP/OpenAPI/MCP let you point at external endpoints. All tool calls
        are gated by OPA policy and audited.
      </p>

      {error && <div style={{ ...card, borderColor: colors.danger }}>{error}</div>}

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Register a tool</h3>
        <form onSubmit={create} style={{ display: "grid", gap: "0.5rem", gridTemplateColumns: "1fr 1fr" }}>
          <select
            style={input}
            value={kind}
            onChange={(e) => setKind(e.target.value as ToolKind)}
          >
            {KINDS.map((k) => (
              <option key={k} value={k}>{k}</option>
            ))}
          </select>

          {kind === "builtin" ? (
            <select
              style={input}
              value={chosenBuiltin}
              onChange={(e) => setChosenBuiltin(e.target.value)}
            >
              {builtins.map((b) => (
                <option key={b.name} value={b.name}>
                  {b.name} — {b.description}
                </option>
              ))}
            </select>
          ) : (
            <input
              style={input}
              placeholder="custom name (e.g. jira_search)"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          )}

          {kind !== "builtin" && (
            <input
              style={{ ...input, gridColumn: "span 2" }}
              placeholder={
                kind === "openapi"
                  ? "server_url (e.g. https://api.example.com/v1)"
                  : "endpoint URL"
              }
              value={endpoint}
              onChange={(e) => setEndpoint(e.target.value)}
              required
            />
          )}

          <input
            style={input}
            placeholder="scopes (comma-separated, e.g. safe,internal)"
            value={scopes}
            onChange={(e) => setScopes(e.target.value)}
          />
          <button style={button} type="submit">Register</button>
        </form>
      </div>

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Registered tools</h3>
        {tools.length === 0 ? (
          <p style={{ color: colors.muted }}>None yet.</p>
        ) : (
          <div style={{ display: "grid", gap: "0.75rem" }}>
            {tools.map((t) => (
              <div
                key={t.id}
                style={{
                  background: colors.bg,
                  border: `1px solid ${colors.bg3}`,
                  borderRadius: 8,
                  padding: "0.75rem 1rem",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
                  <strong>{t.name}</strong>
                  <span style={tag}>{t.kind}</span>
                  {t.scopes.map((s) => (
                    <span key={s} style={{ ...tag, color: colors.accent, borderColor: colors.accent }}>
                      {s}
                    </span>
                  ))}
                  {!t.enabled && (
                    <span style={{ ...tag, color: colors.danger, borderColor: colors.danger }}>
                      disabled
                    </span>
                  )}
                  <div style={{ marginLeft: "auto", display: "flex", gap: "0.35rem" }}>
                    <button
                      style={buttonSecondary}
                      onClick={async () => {
                        try {
                          await api.updateTool(wsId, t.id, { enabled: !t.enabled });
                          await reload();
                        } catch (e) {
                          setError(String(e));
                        }
                      }}
                    >
                      {t.enabled ? "Disable" : "Enable"}
                    </button>
                    <button
                      style={{
                        ...buttonSecondary,
                        color: colors.danger,
                        borderColor: colors.danger,
                      }}
                      onClick={async () => {
                        if (!confirm(`Delete '${t.name}'?`)) return;
                        try {
                          await api.deleteTool(wsId, t.id);
                          await reload();
                        } catch (e) {
                          setError(String(e));
                        }
                      }}
                    >
                      Delete
                    </button>
                  </div>
                </div>
                {t.description && (
                  <div style={{ color: colors.muted, fontSize: 13, marginTop: "0.25rem" }}>
                    {t.description}
                  </div>
                )}
                <div style={{ marginTop: "0.5rem", display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                  <input
                    style={{ ...input, flex: "1 1 240px", fontFamily: "ui-monospace, monospace", fontSize: 12 }}
                    placeholder='{"url": "https://example.com"}'
                    value={invokeArgs[t.id] ?? ""}
                    onChange={(e) =>
                      setInvokeArgs((prev) => ({ ...prev, [t.id]: e.target.value }))
                    }
                  />
                  <button
                    style={button}
                    onClick={async () => {
                      try {
                        const argsRaw = invokeArgs[t.id] ?? "{}";
                        const args = JSON.parse(argsRaw || "{}");
                        const r = await api.invokeTool(wsId, t.id, args);
                        setInvokeResult((prev) => ({
                          ...prev,
                          [t.id]: JSON.stringify(r, null, 2),
                        }));
                      } catch (e) {
                        setInvokeResult((prev) => ({ ...prev, [t.id]: String(e) }));
                      }
                    }}
                  >
                    Invoke
                  </button>
                </div>
                {invokeResult[t.id] && (
                  <pre
                    style={{
                      marginTop: "0.5rem",
                      background: "#000",
                      padding: "0.75rem",
                      borderRadius: 6,
                      maxHeight: 240,
                      overflow: "auto",
                      fontSize: 12,
                    }}
                  >
                    {invokeResult[t.id]}
                  </pre>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
