"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, HttpError, type Me } from "../lib/api";
import { card, colors, tag } from "../lib/styles";

export default function Home() {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .me()
      .then(setMe)
      .catch((e: unknown) => {
        if (e instanceof HttpError && e.status === 401) {
          // not logged in — that's fine on the landing page
        } else {
          setError(String(e));
        }
      });
  }, []);

  return (
    <div style={{ maxWidth: 880, margin: "0 auto", display: "grid", gap: "1.25rem" }}>
      <header>
        <h1 style={{ fontSize: "2.25rem", margin: "0 0 0.5rem 0" }}>
          AgenticOS <span style={tag}>v0.1 — Phase 1</span>
        </h1>
        <p style={{ opacity: 0.85, lineHeight: 1.55 }}>
          Self-hosted, on-prem agent platform that runs entirely on local LLMs.
          Phase 1 ships authentication and workspace management.
        </p>
      </header>

      {error && (
        <div style={{ ...card, borderColor: colors.danger }}>
          <strong>API error:</strong> {error}
        </div>
      )}

      {me ? (
        <div style={card}>
          <div style={{ display: "flex", alignItems: "baseline", gap: "0.75rem" }}>
            <h2 style={{ margin: 0, fontSize: "1.25rem" }}>
              Welcome, {me.display_name ?? me.email}
            </h2>
            <span style={tag}>{me.is_superuser ? "superuser" : "user"}</span>
          </div>
          <p style={{ margin: "0.5rem 0 1rem 0", color: colors.muted }}>
            You&apos;re a member of {me.workspaces.length} workspace
            {me.workspaces.length === 1 ? "" : "s"}.
          </p>
          <Link href="/workspaces" style={{ color: colors.accent }}>
            → Open workspaces
          </Link>
        </div>
      ) : (
        <div style={card}>
          <h2 style={{ margin: 0, fontSize: "1.25rem" }}>Get started</h2>
          <p style={{ color: colors.muted, marginTop: "0.5rem" }}>
            Click <strong>Log in</strong> in the top-right to authenticate via
            your IdP (Keycloak in dev — username/password{" "}
            <code style={{ color: colors.fg }}>alice / alice</code>).
            You&apos;ll be auto-provisioned into the default tenant.
          </p>
        </div>
      )}

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Service endpoints</h3>
        <ul style={{ lineHeight: 1.85, color: colors.muted }}>
          <li>
            <code style={{ color: colors.fg }}>/api/v1/me</code>,{" "}
            <code style={{ color: colors.fg }}>/api/v1/workspaces</code> — see{" "}
            <a href={`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080"}/docs`} style={{ color: colors.accent }}>
              Swagger UI
            </a>
          </li>
          <li><a href="http://localhost:8090" style={{ color: colors.accent }}>Keycloak</a> — admin/admin</li>
          <li><a href="http://localhost:9001" style={{ color: colors.accent }}>MinIO console</a></li>
          <li><a href="http://localhost:3001" style={{ color: colors.accent }}>Grafana</a> — admin/admin</li>
        </ul>
      </div>
    </div>
  );
}
