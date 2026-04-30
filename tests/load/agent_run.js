// k6: drive synchronous agent runs through the api-gateway.
// Useful for smoke-testing throughput against a real Ollama. Set
// AGENTICOS_AGENT_ID to a tiny chat model (e.g. an alias backed by
// `qwen2.5:1.5b-instruct`) for meaningful numbers.

import http from "k6/http";
import { check } from "k6";

const BASE = __ENV.AGENTICOS_API || "http://localhost:8080";
const TOKEN = __ENV.AGENTICOS_TOKEN;
const WS = __ENV.AGENTICOS_WORKSPACE_ID;
const AGENT = __ENV.AGENTICOS_AGENT_ID;

for (const [name, value] of Object.entries({ TOKEN, WS, AGENT })) {
  if (!value) throw new Error(`set AGENTICOS_${name === "TOKEN" ? "TOKEN" : `${name}_ID`}`);
}

export const options = {
  vus: Number(__ENV.VUS || 5),
  duration: __ENV.DURATION || "60s",
  thresholds: {
    http_req_failed: ["rate<0.02"],
    // First-token / non-stream completion latency target.
    http_req_duration: ["p(95)<8000"],
  },
};

const params = {
  headers: {
    Authorization: `Bearer ${TOKEN}`,
    "Content-Type": "application/json",
  },
  timeout: "120s",
};

const QUESTIONS = [
  "Give me a one-sentence summary of FastAPI.",
  "What is the capital of Norway?",
  "Translate 'hello, world' into Japanese.",
  "List three benefits of ReAct agents.",
];

export default function () {
  const q = QUESTIONS[__VU % QUESTIONS.length];
  const r = http.post(
    `${BASE}/api/v1/workspaces/${WS}/agents/${AGENT}/run`,
    JSON.stringify({ user_message: q }),
    params,
  );
  check(r, {
    "status 200": (resp) => resp.status === 200,
    "got final_message": (resp) => resp.json().final_message,
  });
}
