// Smoke load (01/R9): a few people reading for a short while. Every change can afford it; it catches a journey that
// errors or slows under the lightest concurrency. Thresholds are pass/fail: k6 exits 99 when one is crossed.
// The numbers are STARTERS (01/R1) until a measured baseline replaces them (docs/architecture/capacity.md).
import http from "k6/http";
import { check, sleep } from "k6";
import { BASE_URL, bearer, tokens } from "./common.js";

const humans = tokens("HUMAN_TOKENS");

export const options = {
  scenarios: {
    smoke: { executor: "constant-vus", vus: 2, duration: "15s" },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<500"],
    checks: ["rate==1"],
  },
};

export default function () {
  check(http.get(`${BASE_URL}/health`), { "health answers 200": (r) => r.status === 200 });
  check(http.get(`${BASE_URL}/ready`), { "ready answers 200": (r) => r.status === 200 });
  const token = humans[(__VU + __ITER) % humans.length];
  check(http.get(`${BASE_URL}/work-items?limit=5`, bearer(token)), {
    "a person lists work items": (r) => r.status === 200,
  });
  sleep(1); // a person's pace: well inside the per-person limit, so a 429 here is a real failure
}
