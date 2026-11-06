// Shared by the load scenarios (01/R9). Not a scenario itself: k6 runs smoke.js and mixed.js.

export const BASE_URL = (__ENV.BASE_URL || "").replace(/\/$/, "");
if (!BASE_URL) {
  throw new Error("set BASE_URL (make load-smoke BASE_URL=http://127.0.0.1:8000)");
}

// Comma-separated bearer tokens from the environment. Locally `make load-*` mints dev tokens; against a deployed
// environment the caller passes real ones, because dev tokens are refused anywhere but a local API (05/SG12).
export function tokens(name) {
  const list = (__ENV[name] || "").split(",").map((t) => t.trim()).filter(Boolean);
  if (list.length === 0) {
    throw new Error(`set ${name}: one or more bearer tokens, comma-separated`);
  }
  return list;
}

export function bearer(token) {
  return { headers: { Authorization: `Bearer ${token}` } };
}
