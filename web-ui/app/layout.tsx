import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "AgenticOS",
  description: "Self-hosted Agentic OS for Enterprise — runs entirely on local LLMs.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          fontFamily:
            "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
          background: "#0b0c0f",
          color: "#e7e9ee",
        }}
      >
        {children}
      </body>
    </html>
  );
}
