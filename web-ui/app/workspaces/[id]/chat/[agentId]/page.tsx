"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, chatWebSocketUrl, type RunResultBody } from "../../../../../lib/api";
import { button, card, colors, input, tag } from "../../../../../lib/styles";

interface UIEvent {
  type: string;
  payload: Record<string, any>;
  id: number;
}

let eventCounter = 0;

export default function ChatPage() {
  const params = useParams<{ id: string; agentId: string }>();
  const wsId = params.id;
  const agentId = params.agentId;

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [events, setEvents] = useState<UIEvent[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scroller.current) {
      scroller.current.scrollTop = scroller.current.scrollHeight;
    }
  }, [events]);

  useEffect(() => {
    if (!agentId) return;
    let cancelled = false;
    (async () => {
      try {
        const s = await api.createSession(wsId, agentId, {});
        if (cancelled) return;
        setSessionId(s.id);
        const ws = new WebSocket(chatWebSocketUrl(agentId, s.id));
        wsRef.current = ws;
        ws.onopen = () => setConnected(true);
        ws.onclose = () => setConnected(false);
        ws.onerror = (e) => {
          console.error(e);
          setError("WebSocket error");
        };
        ws.onmessage = (msg) => {
          try {
            const ev = JSON.parse(msg.data);
            setEvents((prev) => [
              ...prev,
              { ...ev, id: eventCounter++ },
            ]);
            if (ev.type === "final" || ev.type === "error" || ev.type === "done") {
              setBusy(false);
            }
          } catch {
            /* ignore */
          }
        };
      } catch (e) {
        setError(String(e));
      }
    })();
    return () => {
      cancelled = true;
      wsRef.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsId, agentId]);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const ws = wsRef.current;
    const text = draft.trim();
    if (!ws || ws.readyState !== ws.OPEN || !text) return;
    setEvents((prev) => [
      ...prev,
      {
        id: eventCounter++,
        type: "user_message",
        payload: { content: text },
      },
    ]);
    ws.send(JSON.stringify({ type: "user_message", content: text }));
    setDraft("");
    setBusy(true);
  }

  return (
    <div style={{ maxWidth: 980, margin: "0 auto", display: "grid", gap: "1rem" }}>
      <Link href={`/workspaces/${wsId}/agents`} style={{ color: colors.muted, fontSize: 14 }}>
        ← Agents
      </Link>
      <div style={{ display: "flex", alignItems: "baseline", gap: "0.75rem" }}>
        <h1 style={{ margin: 0 }}>Chat</h1>
        <span style={{ ...tag, color: connected ? colors.ok : colors.muted, borderColor: connected ? colors.ok : colors.muted }}>
          {connected ? "connected" : "connecting…"}
        </span>
        {sessionId && (
          <span style={{ color: colors.muted, fontSize: 12 }}>session {sessionId.slice(0, 8)}</span>
        )}
      </div>

      {error && <div style={{ ...card, borderColor: colors.danger }}>{error}</div>}

      <div
        ref={scroller}
        style={{
          ...card,
          height: "55vh",
          overflowY: "auto",
          display: "grid",
          gap: "0.5rem",
          padding: "1rem",
        }}
      >
        {events.length === 0 ? (
          <div style={{ color: colors.muted }}>Send a message to begin.</div>
        ) : (
          events.map((ev) => <EventBubble key={ev.id} ev={ev} />)
        )}
        {busy && (
          <div style={{ color: colors.muted, fontStyle: "italic" }}>thinking…</div>
        )}
      </div>

      <form onSubmit={send} style={{ display: "flex", gap: "0.5rem" }}>
        <input
          style={{ ...input, flex: 1 }}
          placeholder="Ask the agent…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={!connected || busy}
        />
        <button style={button} type="submit" disabled={!connected || busy}>
          Send
        </button>
      </form>
    </div>
  );
}

function EventBubble({ ev }: { ev: UIEvent }) {
  if (ev.type === "user_message") {
    return (
      <div style={{ alignSelf: "flex-end", maxWidth: "75%" }}>
        <div style={{ ...userBubble }}>{ev.payload.content}</div>
      </div>
    );
  }
  if (ev.type === "final") {
    return (
      <div style={{ alignSelf: "flex-start", maxWidth: "85%" }}>
        <div style={assistantBubble}>{ev.payload.content}</div>
        {Array.isArray(ev.payload.citations) && ev.payload.citations.length > 0 && (
          <div style={{ color: colors.muted, fontSize: 12, marginTop: "0.35rem" }}>
            citations:{" "}
            {ev.payload.citations.map((c: any, i: number) => (
              <span key={i} style={{ marginRight: "0.5rem" }}>
                [{i + 1}] {c.document_title}
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }
  if (ev.type === "tool_call") {
    return (
      <div style={{ ...metaBubble, color: colors.accent }}>
        🛠 calling <strong>{ev.payload.name}</strong>(
        <code style={{ fontSize: 12 }}>{JSON.stringify(ev.payload.args)}</code>)
      </div>
    );
  }
  if (ev.type === "tool_result") {
    return (
      <div style={{ ...metaBubble, color: ev.payload.ok ? colors.ok : colors.danger }}>
        ↩ {ev.payload.name}{" "}
        {ev.payload.ok ? (
          <span style={{ color: colors.muted, fontSize: 12 }}>ok</span>
        ) : (
          <span style={{ color: colors.danger }}>{ev.payload.error}</span>
        )}
      </div>
    );
  }
  if (ev.type === "citations") {
    return (
      <div style={{ ...metaBubble, color: colors.muted }}>
        🔎 retrieved {ev.payload.hits?.length ?? 0} chunks
      </div>
    );
  }
  if (ev.type === "step") {
    return null;
  }
  if (ev.type === "error") {
    return (
      <div style={{ ...metaBubble, color: colors.danger }}>error: {ev.payload.message}</div>
    );
  }
  return null;
}

const userBubble: React.CSSProperties = {
  background: colors.accent,
  color: "#0b0c0f",
  padding: "0.55rem 0.85rem",
  borderRadius: 12,
  whiteSpace: "pre-wrap",
};
const assistantBubble: React.CSSProperties = {
  background: colors.bg2,
  color: colors.fg,
  padding: "0.55rem 0.85rem",
  borderRadius: 12,
  border: `1px solid ${colors.bg3}`,
  whiteSpace: "pre-wrap",
};
const metaBubble: React.CSSProperties = {
  fontSize: 13,
  alignSelf: "flex-start",
};
