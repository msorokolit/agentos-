"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  api,
  type Model,
  type ModelKind,
  type ModelProvider,
  type ModelTestResult,
} from "../../../lib/api";
import { button, buttonSecondary, card, colors, input, tag } from "../../../lib/styles";

const PROVIDERS: ModelProvider[] = ["ollama", "vllm", "openai_compat"];
const KINDS: ModelKind[] = ["chat", "embedding"];

const DEFAULT_ENDPOINTS: Record<ModelProvider, string> = {
  ollama: "http://ollama:11434",
  vllm: "http://vllm:8000",
  openai_compat: "http://your-endpoint:8000",
};

export default function ModelsPage() {
  const [models, setModels] = useState<Model[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tested, setTested] = useState<Record<string, ModelTestResult>>({});

  // Form state
  const [alias, setAlias] = useState("chat-default");
  const [provider, setProvider] = useState<ModelProvider>("ollama");
  const [endpoint, setEndpoint] = useState(DEFAULT_ENDPOINTS["ollama"]);
  const [modelName, setModelName] = useState("qwen2.5:7b-instruct");
  const [kind, setKind] = useState<ModelKind>("chat");

  async function reload() {
    try {
      setModels(await api.listModels());
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    reload();
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.createModel({ alias, provider, endpoint, model_name: modelName, kind });
      setAlias("");
      await reload();
    } catch (e2) {
      setError(String(e2));
    }
  }

  async function runTest(id: string) {
    try {
      const r = await api.testModel(id);
      setTested((prev) => ({ ...prev, [id]: r }));
    } catch (e) {
      setError(String(e));
    }
  }

  async function toggle(m: Model) {
    try {
      await api.updateModel(m.id, { enabled: !m.enabled });
      await reload();
    } catch (e) {
      setError(String(e));
    }
  }

  async function remove(m: Model) {
    if (!confirm(`Delete model alias '${m.alias}'?`)) return;
    try {
      await api.deleteModel(m.id);
      await reload();
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <div style={{ maxWidth: 980, margin: "0 auto", display: "grid", gap: "1.25rem" }}>
      <Link href="/admin" style={{ color: colors.muted, fontSize: 14 }}>
        ← Admin
      </Link>
      <h1 style={{ margin: 0 }}>Models</h1>
      <p style={{ color: colors.muted, marginTop: 0 }}>
        Register chat + embedding models served by Ollama, vLLM, or any
        OpenAI-compatible endpoint. Aliases are used by agents.
      </p>

      {error && <div style={{ ...card, borderColor: colors.danger }}>{error}</div>}

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Register a model</h3>
        <form onSubmit={create} style={{ display: "grid", gap: "0.5rem", gridTemplateColumns: "1fr 1fr" }}>
          <input
            style={input}
            placeholder="alias (e.g. chat-default)"
            value={alias}
            onChange={(e) => setAlias(e.target.value)}
            required
          />
          <select
            style={input}
            value={provider}
            onChange={(e) => {
              const p = e.target.value as ModelProvider;
              setProvider(p);
              setEndpoint(DEFAULT_ENDPOINTS[p]);
            }}
          >
            {PROVIDERS.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
          <input
            style={input}
            placeholder="endpoint URL"
            value={endpoint}
            onChange={(e) => setEndpoint(e.target.value)}
            required
          />
          <input
            style={input}
            placeholder="upstream model_name"
            value={modelName}
            onChange={(e) => setModelName(e.target.value)}
            required
          />
          <select
            style={input}
            value={kind}
            onChange={(e) => setKind(e.target.value as ModelKind)}
          >
            {KINDS.map((k) => (
              <option key={k} value={k}>{k}</option>
            ))}
          </select>
          <button style={button} type="submit">Register</button>
        </form>
      </div>

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Registered models</h3>
        {models.length === 0 ? (
          <p style={{ color: colors.muted }}>No models registered yet.</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
            <thead>
              <tr style={{ textAlign: "left", color: colors.muted, fontSize: 12 }}>
                <th style={th}>Alias</th>
                <th style={th}>Provider</th>
                <th style={th}>Model</th>
                <th style={th}>Kind</th>
                <th style={th}>Status</th>
                <th style={th}>Test</th>
                <th style={th} />
              </tr>
            </thead>
            <tbody>
              {models.map((m) => {
                const t = tested[m.id];
                return (
                  <tr key={m.id}>
                    <td style={td}>
                      <code style={{ color: colors.fg }}>{m.alias}</code>
                    </td>
                    <td style={td}>{m.provider}</td>
                    <td style={td}>
                      <span style={{ color: colors.muted, fontFamily: "ui-monospace, monospace" }}>
                        {m.model_name}
                      </span>
                      <br />
                      <span style={{ color: colors.muted, fontSize: 12 }}>{m.endpoint}</span>
                    </td>
                    <td style={td}>{m.kind}</td>
                    <td style={td}>
                      {m.enabled ? (
                        <span style={{ ...tag, color: colors.ok, borderColor: colors.ok }}>
                          enabled
                        </span>
                      ) : (
                        <span style={{ ...tag, color: colors.danger, borderColor: colors.danger }}>
                          disabled
                        </span>
                      )}
                    </td>
                    <td style={td}>
                      {t ? (
                        t.ok ? (
                          <span style={{ color: colors.ok }}>✔ {t.latency_ms}ms</span>
                        ) : (
                          <span style={{ color: colors.danger }}>✘ {t.detail ?? "fail"}</span>
                        )
                      ) : (
                        <span style={{ color: colors.muted }}>—</span>
                      )}
                    </td>
                    <td style={{ ...td, display: "flex", gap: "0.35rem", justifyContent: "flex-end" }}>
                      <button style={buttonSecondary} onClick={() => runTest(m.id)}>
                        Ping
                      </button>
                      <button style={buttonSecondary} onClick={() => toggle(m)}>
                        {m.enabled ? "Disable" : "Enable"}
                      </button>
                      <button
                        style={{
                          ...buttonSecondary,
                          color: colors.danger,
                          borderColor: colors.danger,
                        }}
                        onClick={() => remove(m)}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

const th = {
  padding: "0.5rem 0.5rem",
  borderBottom: `1px solid ${colors.bg3}`,
} as const;
const td = {
  padding: "0.5rem 0.5rem",
  borderBottom: `1px solid ${colors.bg3}`,
  verticalAlign: "top" as const,
};
