// Mixed traffic (01/R3, R4, R9): people and an agent at the same time. Agents are a traffic class of their own with
// their own, lower limits (security/rate_limit.py), so an agent bursting past its limit gets 429 + Retry-After while
// people keep their latency and never see a 429. Thresholds are pass/fail: k6 exits 99 when one is crossed.
// The rates and the p95 are STARTERS (01/R1): set them from the capacity assumptions and a measured baseline.
import http from "k6/http";
import { check } from "k6";
import { Counter, Rate } from "k6/metrics";
import { BASE_URL, bearer, tokens } from "./common.js";

const humans = tokens("HUMAN_TOKENS");
const agent = tokens("AGENT_TOKEN")[0];

const humanLimited = new Counter("human_limited");
const agentLimited = new Rate("agent_limited");
const agentUnexpected = new Rate("agent_unexpected");
const retryAfter = new Rate("limited_with_retry_after");

export const options = {
  scenarios: {
    // Several people, each well inside the human read limit (20/s per person).
    humans: {
      executor: "constant-arrival-rate", exec: "human", rate: 20, timeUnit: "1s", duration: "30s",
      preAllocatedVUs: 20, maxVUs: 60,
    },
    // One agent at 15/s: a rate a person may use (20/s) but an agent may not (10/s, burst 20). About 30% of its
    // requests must be refused; if agents shared the human limits, none would be and the run fails.
    agents: {
      executor: "constant-arrival-rate", exec: "agentBurst", rate: 15, timeUnit: "1s", duration: "30s",
      preAllocatedVUs: 20, maxVUs: 80,
    },
  },
  thresholds: {
    "http_req_duration{scenario:humans}": ["p(95)<300"],
    "http_req_failed{scenario:humans}": ["rate<0.01"],
    "dropped_iterations{scenario:humans}": ["count==0"],
    human_limited: ["count==0"],
    agent_limited: ["rate>0.1"],
    agent_unexpected: ["rate==0"],
    limited_with_retry_after: ["rate==1"],
  },
};

export function human() {
  const r = http.get(`${BASE_URL}/work-items?limit=5`, bearer(humans[(__VU + __ITER) % humans.length]));
  humanLimited.add(r.status === 429 ? 1 : 0);
  check(r, { "a person is answered": (res) => res.status === 200 });
}

export function agentBurst() {
  // 429 is the expected answer to an agent over its limit, so it doesn't count as a failed request.
  const r = http.get(`${BASE_URL}/work-items?limit=5`, {
    ...bearer(agent),
    responseCallback: http.expectedStatuses(200, 429),
  });
  agentLimited.add(r.status === 429);
  agentUnexpected.add(r.status !== 200 && r.status !== 429);
  if (r.status === 429) {
    retryAfter.add(Number(r.headers["Retry-After"]) >= 1);
  }
}
