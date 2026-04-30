"use client";

import { useEffect, useState } from "react";
import { api, type Me } from "../../lib/api";
import { card, colors } from "../../lib/styles";

export default function AdminPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.me().then(setMe).catch((e) => setError(String(e)));
  }, []);

  if (error) {
    return (
      <div style={{ ...card, borderColor: colors.danger, maxWidth: 880, margin: "0 auto" }}>
        {error}
      </div>
    );
  }
  if (!me) return null;

  const isAdmin =
    me.is_superuser ||
    me.workspaces.some((w) => w.role === "admin" || w.role === "owner");

  return (
    <div style={{ maxWidth: 880, margin: "0 auto", display: "grid", gap: "1.25rem" }}>
      <h1 style={{ margin: 0 }}>Admin</h1>
      {!isAdmin ? (
        <div style={card}>
          <p style={{ margin: 0, color: colors.muted }}>
            You don&apos;t have admin access in any workspace. Ask an owner to
            grant you the <code style={{ color: colors.fg }}>admin</code> role.
          </p>
        </div>
      ) : (
        <>
          <div style={card}>
            <h3 style={{ marginTop: 0 }}>Coming in Phase 2 +</h3>
            <ul style={{ color: colors.muted, lineHeight: 1.85 }}>
              <li>Models registry (Ollama / vLLM)</li>
              <li>Tools registry (MCP / HTTP / built-ins)</li>
              <li>Audit log explorer</li>
              <li>Policy bundles (OPA)</li>
            </ul>
          </div>
        </>
      )}
    </div>
  );
}
