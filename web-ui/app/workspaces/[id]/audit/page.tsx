"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type AuditRow } from "../../../../lib/api";
import { button, card, colors, input, tag } from "../../../../lib/styles";

const DECISION_COLOR: Record<AuditRow["decision"], string> = {
  allow: colors.ok,
  deny: colors.danger,
  error: colors.danger,
};

export default function AuditPage() {
  const params = useParams<{ id: string }>();
  const wsId = params.id;
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [filterAction, setFilterAction] = useState("");
  const [filterActor, setFilterActor] = useState("");

  async function reload() {
    try {
      setRows(
        await api.audit(wsId, {
          action: filterAction || undefined,
          actor: filterActor || undefined,
          limit: 200,
        }),
      );
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    if (wsId) reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsId]);

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", display: "grid", gap: "1rem" }}>
      <Link href={`/workspaces`} style={{ color: colors.muted, fontSize: 14 }}>
        ← Workspaces
      </Link>
      <h1 style={{ margin: 0 }}>Audit</h1>
      <p style={{ color: colors.muted, marginTop: 0 }}>
        Append-only log of every mutating action and every LLM/tool
        invocation. Visible to admins.
      </p>

      {error && <div style={{ ...card, borderColor: colors.danger }}>{error}</div>}

      <div style={card}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            reload();
          }}
          style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}
        >
          <input
            style={{ ...input, flex: "1 1 200px" }}
            placeholder="action (e.g. agent.run)"
            value={filterAction}
            onChange={(e) => setFilterAction(e.target.value)}
          />
          <input
            style={{ ...input, flex: "1 1 200px" }}
            placeholder="actor email contains…"
            value={filterActor}
            onChange={(e) => setFilterActor(e.target.value)}
          />
          <button style={button} type="submit">Filter</button>
        </form>
      </div>

      <div style={card}>
        {rows.length === 0 ? (
          <p style={{ color: colors.muted }}>No matching audit events.</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ textAlign: "left", color: colors.muted, fontSize: 11 }}>
                <th style={th}>When</th>
                <th style={th}>Actor</th>
                <th style={th}>Action</th>
                <th style={th}>Resource</th>
                <th style={th}>Decision</th>
                <th style={th}>Payload</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td style={{ ...td, color: colors.muted, whiteSpace: "nowrap" }}>
                    {r.created_at
                      ? new Date(r.created_at).toLocaleString()
                      : "—"}
                  </td>
                  <td style={td}>{r.actor_email ?? "—"}</td>
                  <td style={td}>
                    <code style={{ color: colors.fg }}>{r.action}</code>
                  </td>
                  <td style={{ ...td, color: colors.muted }}>
                    {r.resource_type
                      ? `${r.resource_type}:${(r.resource_id ?? "").slice(0, 8)}`
                      : "—"}
                  </td>
                  <td style={td}>
                    <span
                      style={{
                        ...tag,
                        color: DECISION_COLOR[r.decision],
                        borderColor: DECISION_COLOR[r.decision],
                      }}
                    >
                      {r.decision}
                    </span>
                  </td>
                  <td style={{ ...td, fontFamily: "ui-monospace, monospace", fontSize: 11 }}>
                    {Object.keys(r.payload).length > 0
                      ? JSON.stringify(r.payload)
                      : ""}
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
  padding: "0.4rem 0.5rem",
  borderBottom: `1px solid ${colors.bg3}`,
};
