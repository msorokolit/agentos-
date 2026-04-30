import Link from "next/link";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

export default function Home() {
  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "2rem",
      }}
    >
      <div style={{ maxWidth: 720, lineHeight: 1.55 }}>
        <h1 style={{ fontSize: "2.25rem", marginBottom: "0.5rem" }}>
          AgenticOS <span style={{ opacity: 0.5, fontSize: "1rem" }}>v0.1 — Phase 0</span>
        </h1>
        <p style={{ opacity: 0.85 }}>
          Self-hosted, on-prem agent platform that runs entirely on local LLMs. The web UI will
          land in Phase 1; for now you can poke around the services directly.
        </p>

        <h2 style={{ marginTop: "2rem", fontSize: "1.1rem", opacity: 0.9 }}>Service endpoints</h2>
        <ul>
          <li>
            <Link href={`${apiUrl}/healthz`}>{apiUrl}/healthz</Link> — API gateway
          </li>
          <li>
            <Link href={`${apiUrl}/openapi.json`}>{apiUrl}/openapi.json</Link> — OpenAPI schema
          </li>
          <li>
            <a href="http://localhost:8090">http://localhost:8090</a> — Keycloak (admin/admin)
          </li>
          <li>
            <a href="http://localhost:9001">http://localhost:9001</a> — MinIO console
          </li>
          <li>
            <a href="http://localhost:3001">http://localhost:3001</a> — Grafana (admin/admin)
          </li>
        </ul>
      </div>
    </main>
  );
}
