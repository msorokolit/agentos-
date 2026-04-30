"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  api,
  type AgentRow,
  type Tool,
} from "../../../../lib/api";
import {
  button,
  buttonSecondary,
  card,
  colors,
  input,
  tag,
} from "../../../../lib/styles";

export default function AgentsPage() {
  const params = useParams<{ id: string }>();
  const wsId = params.id;

  const [agents, setAgents] = useState<AgentRow[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Form
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [systemPrompt, setSystemPrompt] = useState(
    "You are a helpful assistant.",
  );
  const [modelAlias, setModelAlias] = useState("chat-default");
  const [toolIds, setToolIds] = useState<string[]>([]);
  const [ragEnabled, setRagEnabled] = useState(false);

  async function reload() {
    try {
      const [a, t] = await Promise.all([api.listAgents(wsId), api.listTools(wsId)]);
      setAgents(a);
      setTools(t);
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
      await api.createAgent(wsId, {
        name,
        slug,
        system_prompt: systemPrompt,
        model_alias: modelAlias,
        tool_ids: toolIds,
        config: ragEnabled ? { rag_enabled: true } : {},
      });
      setName("");
      setSlug("");
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
      <h1 style={{ margin: 0 }}>Agents</h1>

      {error && <div style={{ ...card, borderColor: colors.danger }}>{error}</div>}

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>New agent</h3>
        <form onSubmit={create} style={{ display: "grid", gap: "0.5rem", gridTemplateColumns: "1fr 1fr" }}>
          <input
            style={input}
            placeholder="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <input
            style={input}
            placeholder="slug (lower-case)"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            required
            pattern="^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$"
          />
          <input
            style={{ ...input, gridColumn: "span 2" }}
            placeholder="model alias (e.g. chat-default)"
            value={modelAlias}
            onChange={(e) => setModelAlias(e.target.value)}
            required
          />
          <textarea
            style={{ ...input, gridColumn: "span 2", minHeight: 80, fontFamily: "ui-monospace, monospace" }}
            placeholder="system prompt"
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
          />
          <div style={{ gridColumn: "span 2" }}>
            <div style={{ color: colors.muted, fontSize: 12, marginBottom: "0.25rem" }}>
              Bind tools
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.35rem" }}>
              {tools.length === 0 ? (
                <span style={{ color: colors.muted, fontSize: 13 }}>
                  No tools yet — register some on the Tools page.
                </span>
              ) : (
                tools.map((t) => (
                  <label
                    key={t.id}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "0.35rem",
                      background: colors.bg,
                      border: `1px solid ${colors.bg3}`,
                      borderRadius: 6,
                      padding: "0.25rem 0.5rem",
                      fontSize: 13,
                      cursor: "pointer",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={toolIds.includes(t.id)}
                      onChange={(e) =>
                        setToolIds((prev) =>
                          e.target.checked
                            ? [...prev, t.id]
                            : prev.filter((x) => x !== t.id),
                        )
                      }
                    />
                    {t.name}
                  </label>
                ))
              )}
            </div>
          </div>
          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", color: colors.muted }}>
            <input
              type="checkbox"
              checked={ragEnabled}
              onChange={(e) => setRagEnabled(e.target.checked)}
            />
            Enable RAG (workspace knowledge)
          </label>
          <button style={button} type="submit">Create agent</button>
        </form>
      </div>

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Agents</h3>
        {agents.length === 0 ? (
          <p style={{ color: colors.muted }}>None yet.</p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: "0.5rem" }}>
            {agents.map((a) => (
              <li
                key={a.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "0.75rem",
                  padding: "0.75rem 1rem",
                  background: colors.bg,
                  border: `1px solid ${colors.bg3}`,
                  borderRadius: 8,
                }}
              >
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600 }}>{a.name}</div>
                  <div style={{ color: colors.muted, fontSize: 12 }}>
                    {a.slug} · model {a.model_alias} · {a.tool_ids.length} tool
                    {a.tool_ids.length === 1 ? "" : "s"}
                  </div>
                </div>
                {!a.enabled && (
                  <span style={{ ...tag, color: colors.danger, borderColor: colors.danger }}>disabled</span>
                )}
                <Link
                  href={`/workspaces/${wsId}/chat/${a.id}`}
                  style={{ ...button, textDecoration: "none" }}
                >
                  Chat →
                </Link>
                <button
                  style={{ ...buttonSecondary, color: colors.danger, borderColor: colors.danger }}
                  onClick={async () => {
                    if (!confirm(`Delete agent '${a.name}'?`)) return;
                    try {
                      await api.deleteAgent(wsId, a.id);
                      await reload();
                    } catch (e) {
                      setError(String(e));
                    }
                  }}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
