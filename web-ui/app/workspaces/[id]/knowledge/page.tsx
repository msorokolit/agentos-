"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  api,
  type DocumentRow,
  type SearchResponse,
} from "../../../../lib/api";
import {
  button,
  buttonSecondary,
  card,
  colors,
  input,
  tag,
} from "../../../../lib/styles";

const STATUS_COLOR: Record<DocumentRow["status"], string> = {
  pending: colors.muted,
  parsing: colors.accent,
  embedding: colors.accent,
  ready: colors.ok,
  failed: colors.danger,
};

export default function KnowledgePage() {
  const params = useParams<{ id: string }>();
  const wsId = params.id;
  const [docs, setDocs] = useState<DocumentRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResponse | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function reload() {
    try {
      setDocs(await api.listDocuments(wsId));
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    if (wsId) reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsId]);

  async function onUpload(e: React.FormEvent) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      await api.uploadDocument(wsId, file);
      if (fileRef.current) fileRef.current.value = "";
      await reload();
    } catch (e2) {
      setError(String(e2));
    } finally {
      setUploading(false);
    }
  }

  async function runSearch(e: React.FormEvent) {
    e.preventDefault();
    try {
      setResults(await api.search(wsId, query, 5));
      setError(null);
    } catch (e2) {
      setError(String(e2));
    }
  }

  return (
    <div style={{ maxWidth: 980, margin: "0 auto", display: "grid", gap: "1.25rem" }}>
      <Link href="/workspaces" style={{ color: colors.muted, fontSize: 14 }}>
        ← Workspaces
      </Link>
      <h1 style={{ margin: 0 }}>Knowledge</h1>
      <p style={{ color: colors.muted, marginTop: 0 }}>
        Upload PDF, HTML, Markdown, or text. Documents are chunked and
        embedded. Hybrid (vector + keyword) search returns citations.
      </p>

      {error && <div style={{ ...card, borderColor: colors.danger }}>{error}</div>}

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Upload</h3>
        <form
          onSubmit={onUpload}
          style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}
        >
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.txt,.md,.markdown,.html,.htm,.csv,.json"
            style={{ ...input, flex: "1 1 320px" }}
            required
          />
          <button style={button} type="submit" disabled={uploading}>
            {uploading ? "Uploading…" : "Upload"}
          </button>
        </form>
      </div>

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Search</h3>
        <form
          onSubmit={runSearch}
          style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}
        >
          <input
            style={{ ...input, flex: "1 1 320px" }}
            placeholder="ask a question"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            required
          />
          <button style={button} type="submit">Search</button>
        </form>
        {results && (
          <div style={{ marginTop: "1rem", display: "grid", gap: "0.5rem" }}>
            <p style={{ color: colors.muted, fontSize: 13 }}>
              {results.hits.length} hit
              {results.hits.length === 1 ? "" : "s"} for{" "}
              <em>“{results.query}”</em>
            </p>
            {results.hits.map((h) => (
              <div
                key={h.chunk_id}
                style={{
                  background: colors.bg,
                  border: `1px solid ${colors.bg3}`,
                  borderRadius: 8,
                  padding: "0.75rem 1rem",
                }}
              >
                <div style={{ fontSize: 12, color: colors.muted }}>
                  <strong style={{ color: colors.fg }}>{h.document_title}</strong>{" "}
                  · chunk #{h.ord} · score {h.score.toFixed(3)}
                </div>
                <div style={{ marginTop: "0.35rem", whiteSpace: "pre-wrap" }}>
                  {h.text}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Documents</h3>
        {docs.length === 0 ? (
          <p style={{ color: colors.muted }}>No documents uploaded.</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
            <thead>
              <tr style={{ textAlign: "left", color: colors.muted, fontSize: 12 }}>
                <th style={th}>Title</th>
                <th style={th}>MIME</th>
                <th style={th}>Chunks</th>
                <th style={th}>Status</th>
                <th style={th}>Created</th>
                <th style={th} />
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td style={td}>{d.title}</td>
                  <td style={td}>{d.mime ?? "—"}</td>
                  <td style={td}>{d.chunk_count}</td>
                  <td style={td}>
                    <span
                      style={{
                        ...tag,
                        color: STATUS_COLOR[d.status],
                        borderColor: STATUS_COLOR[d.status],
                      }}
                    >
                      {d.status}
                    </span>
                  </td>
                  <td style={{ ...td, color: colors.muted }}>
                    {new Date(d.created_at).toLocaleString()}
                  </td>
                  <td style={{ ...td, textAlign: "right" }}>
                    <button
                      style={buttonSecondary}
                      onClick={async () => {
                        if (!confirm(`Delete '${d.title}'?`)) return;
                        try {
                          await api.deleteDocument(wsId, d.id);
                          await reload();
                        } catch (e) {
                          setError(String(e));
                        }
                      }}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
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
