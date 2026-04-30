"use client";

import Link from "next/link";
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
        <div style={card}>
          <h3 style={{ marginTop: 0 }}>Sections</h3>
          <ul style={{ lineHeight: 1.85, listStyle: "none", padding: 0 }}>
            <li>
              <Link href="/admin/models" style={{ color: colors.accent }}>
                → Models
              </Link>
              <span style={{ color: colors.muted, marginLeft: "0.5rem", fontSize: 13 }}>
                Register Ollama / vLLM endpoints; ping & enable/disable
              </span>
            </li>
            <li style={{ color: colors.muted }}>
              <span style={{ opacity: 0.6 }}>→ Tools (Phase 4)</span>
            </li>
            <li style={{ color: colors.muted }}>
              <span style={{ opacity: 0.6 }}>→ Audit log (Phase 6)</span>
            </li>
            <li style={{ color: colors.muted }}>
              <span style={{ opacity: 0.6 }}>→ Policy bundles (Phase 4)</span>
            </li>
          </ul>
        </div>
      )}
    </div>
  );
}
