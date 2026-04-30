// k6 baseline: hammer /healthz on the api-gateway and assert SLOs.
// Usage: AGENTICOS_API=http://localhost:8080 k6 run tests/load/healthz.js

import http from "k6/http";
import { check, sleep } from "k6";

const BASE = __ENV.AGENTICOS_API || "http://localhost:8080";

export const options = {
  vus: 50,
  duration: __ENV.DURATION || "30s",
  thresholds: {
    http_req_failed: ["rate<0.001"],
    http_req_duration: ["p(99)<50", "p(95)<25"],
  },
};

export default function () {
  const r = http.get(`${BASE}/healthz`);
  check(r, {
    "status 200": (resp) => resp.status === 200,
    "service": (resp) => resp.json().service === "api-gateway",
  });
  sleep(0.05);
}
