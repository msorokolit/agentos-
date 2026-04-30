"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type Member } from "../../../../lib/api";
import { button, card, colors, input } from "../../../../lib/styles";

const ROLES: Member["role"][] = ["viewer", "member", "builder", "admin", "owner"];

export default function MembersPage() {
  const params = useParams<{ id: string }>();
  const wsId = params.id;
  const [members, setMembers] = useState<Member[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Member["role"]>("member");
  const [error, setError] = useState<string | null>(null);

  async function reload() {
    try {
      setMembers(await api.listMembers(wsId));
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    if (wsId) reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsId]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.addMember(wsId, { email, role });
      setEmail("");
      await reload();
    } catch (e2) {
      setError(String(e2));
    }
  }

  return (
    <div style={{ maxWidth: 880, margin: "0 auto", display: "grid", gap: "1.25rem" }}>
      <Link href="/workspaces" style={{ color: colors.muted, fontSize: 14 }}>
        ← Workspaces
      </Link>
      <h1 style={{ margin: 0 }}>Members</h1>

      {error && (
        <div style={{ ...card, borderColor: colors.danger }}>{error}</div>
      )}

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Invite a member</h3>
        <p style={{ color: colors.muted, fontSize: 13, marginTop: 0 }}>
          The user must already exist in the tenant (i.e. they have logged in
          via OIDC at least once).
        </p>
        <form onSubmit={add} style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <input
            style={{ ...input, flex: "2 1 200px" }}
            placeholder="email@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            type="email"
          />
          <select
            style={{ ...input, flex: "1 1 100px" }}
            value={role}
            onChange={(e) => setRole(e.target.value as Member["role"])}
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
          <button style={button} type="submit">Add</button>
        </form>
      </div>

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Current members</h3>
        {members.length === 0 ? (
          <p style={{ color: colors.muted }}>No members yet.</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ textAlign: "left", color: colors.muted, fontSize: 12 }}>
                <th style={{ padding: "0.5rem 0.5rem", borderBottom: `1px solid ${colors.bg3}` }}>
                  Email
                </th>
                <th style={{ padding: "0.5rem 0.5rem", borderBottom: `1px solid ${colors.bg3}` }}>
                  Role
                </th>
                <th style={{ padding: "0.5rem 0.5rem", borderBottom: `1px solid ${colors.bg3}` }} />
              </tr>
            </thead>
            <tbody>
              {members.map((m) => (
                <tr key={m.user_id}>
                  <td style={{ padding: "0.5rem 0.5rem" }}>{m.email}</td>
                  <td style={{ padding: "0.5rem 0.5rem" }}>
                    <select
                      style={{ ...input, padding: "0.25rem 0.5rem" }}
                      value={m.role}
                      onChange={async (e) => {
                        try {
                          await api.updateMember(wsId, m.user_id, {
                            role: e.target.value as Member["role"],
                          });
                          await reload();
                        } catch (e2) {
                          setError(String(e2));
                        }
                      }}
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>{r}</option>
                      ))}
                    </select>
                  </td>
                  <td style={{ padding: "0.5rem 0.5rem", textAlign: "right" }}>
                    <button
                      style={{
                        background: "transparent",
                        border: `1px solid ${colors.danger}`,
                        color: colors.danger,
                        borderRadius: 6,
                        padding: "0.25rem 0.5rem",
                        cursor: "pointer",
                      }}
                      onClick={async () => {
                        if (!confirm(`Remove ${m.email}?`)) return;
                        try {
                          await api.removeMember(wsId, m.user_id);
                          await reload();
                        } catch (e2) {
                          setError(String(e2));
                        }
                      }}
                    >
                      Remove
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
