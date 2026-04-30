// k6: GET /me with an API key. Sanity-check that auth + RBAC paths can
// sustain modest throughput.

import http from "k6/http";
import { check, sleep } from "k6";

const BASE = __ENV.AGENTICOS_API || "http://localhost:8080";
const TOKEN = __ENV.AGENTICOS_TOKEN;
if (!TOKEN) {
  throw new Error("set AGENTICOS_TOKEN to a workspace API key");
}

export const options = {
  vus: Number(__ENV.VUS || 20),
  duration: __ENV.DURATION || "30s",
  thresholds: {
    http_req_failed: ["rate<0.005"],
    http_req_duration: ["p(95)<150"],
  },
};

const params = { headers: { Authorization: `Bearer ${TOKEN}` } };

export default function () {
  const r = http.get(`${BASE}/api/v1/me`, params);
  check(r, {
    "status 200": (resp) => resp.status === 200,
    "has email": (resp) => Boolean(resp.json().email),
  });
  sleep(0.05);
}
