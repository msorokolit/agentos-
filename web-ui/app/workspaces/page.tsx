"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, HttpError, type Workspace } from "../../lib/api";
import { button, card, colors, input, tag } from "../../lib/styles";

export default function WorkspacesPage() {
  const [items, setItems] = useState<Workspace[]>([]);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function reload() {
    try {
      const xs = await api.listWorkspaces();
      setItems(xs);
      setError(null);
    } catch (e) {
      if (e instanceof HttpError && e.status === 401) {
        setError("You must log in to view workspaces.");
      } else {
        setError(String(e));
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    reload();
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.createWorkspace({ name, slug });
      setName("");
      setSlug("");
      await reload();
    } catch (e2) {
      setError(String(e2));
    }
  }

  return (
    <div style={{ maxWidth: 880, margin: "0 auto", display: "grid", gap: "1.25rem" }}>
      <h1 style={{ margin: 0 }}>Workspaces</h1>

      {error && (
        <div style={{ ...card, borderColor: colors.danger }}>
          {error}
        </div>
      )}

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Create workspace</h3>
        <form onSubmit={create} style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <input
            style={{ ...input, flex: "2 1 200px" }}
            placeholder="Name (e.g. Engineering)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <input
            style={{ ...input, flex: "2 1 200px" }}
            placeholder="slug (lower-case, dashes ok)"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            required
            pattern="^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$"
          />
          <button style={button} type="submit">Create</button>
        </form>
      </div>

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Your workspaces</h3>
        {loading ? (
          <p style={{ color: colors.muted }}>Loading…</p>
        ) : items.length === 0 ? (
          <p style={{ color: colors.muted }}>No workspaces yet — create one above.</p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {items.map((w) => (
              <li
                key={w.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "0.75rem",
                  padding: "0.75rem 0",
                  borderBottom: `1px solid ${colors.bg3}`,
                }}
              >
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600 }}>{w.name}</div>
                  <div style={{ color: colors.muted, fontSize: 13 }}>{w.slug}</div>
                </div>
                <span style={tag}>{new Date(w.created_at).toLocaleDateString()}</span>
                <Link href={`/workspaces/${w.id}/knowledge`} style={{ color: colors.accent }}>
                  Knowledge →
                </Link>
                <Link href={`/workspaces/${w.id}/members`} style={{ color: colors.accent }}>
                  Members →
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
