"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";
import { api, type Me } from "../lib/api";
import { button, buttonSecondary, colors } from "../lib/styles";

export function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api
      .me()
      .then((m) => {
        if (!cancelled) setMe(m);
      })
      .catch(() => {
        /* unauthenticated — landing page handles it */
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <nav
        style={{
          padding: "0.75rem 1.5rem",
          borderBottom: `1px solid ${colors.bg3}`,
          display: "flex",
          alignItems: "center",
          gap: "1.5rem",
          background: colors.bg2,
        }}
      >
        <Link
          href="/"
          style={{
            color: colors.fg,
            textDecoration: "none",
            fontWeight: 700,
            fontSize: 18,
          }}
        >
          AgenticOS
        </Link>
        <NavLink href="/" active={pathname === "/"}>Home</NavLink>
        <NavLink href="/workspaces" active={pathname?.startsWith("/workspaces") ?? false}>
          Workspaces
        </NavLink>
        <NavLink href="/admin" active={pathname?.startsWith("/admin") ?? false}>
          Admin
        </NavLink>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "0.75rem" }}>
          {loading ? null : me ? (
            <>
              <span style={{ color: colors.muted, fontSize: 14 }}>{me.email}</span>
              <button
                style={buttonSecondary}
                onClick={async () => {
                  await api.logout();
                  router.refresh();
                  router.push("/");
                }}
              >
                Log out
              </button>
            </>
          ) : (
            <>
              <a
                href={api.devLoginUrl(
                  "alice@agenticos.local",
                  typeof window !== "undefined" ? window.location.href : undefined,
                )}
                style={buttonSecondary}
                title="Dev-only password-less login (disabled in production)"
              >
                Dev login (alice)
              </a>
              <a
                href={api.loginUrl(
                  typeof window !== "undefined" ? window.location.href : undefined,
                )}
                style={button}
              >
                Log in
              </a>
            </>
          )}
        </div>
      </nav>
      <main style={{ padding: "2rem", flex: 1 }}>{children}</main>
    </div>
  );
}

function NavLink({ href, active, children }: { href: string; active: boolean; children: ReactNode }) {
  return (
    <Link
      href={href}
      style={{
        color: active ? colors.fg : colors.muted,
        textDecoration: "none",
        fontSize: 14,
        fontWeight: active ? 600 : 400,
      }}
    >
      {children}
    </Link>
  );
}
