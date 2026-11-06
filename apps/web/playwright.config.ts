// End-to-end on the BUILT artefact (03/F24): the mock issuer, the API on its own e2e database, and the standalone server the image runs.
// `make test-e2e` migrates the database, publishes the issuer key and builds first.
import { defineConfig, devices } from "@playwright/test";

const WEB = "http://127.0.0.1:3100";
// The backend package, kept apart so the server command lines below fit whatever the project name's length.
const PACKAGE = "skeleton_proof_e_next_ai";
const API = "http://127.0.0.1:8100";
const ISSUER = "http://127.0.0.1:9400";
const CLIENT_SECRET = "e2e-only-not-a-secret";
const DATABASE = process.env.E2E_DATABASE_URL;
if (!DATABASE) throw new Error("E2E_DATABASE_URL is not set: the e2e lane needs its own database (06/T10)");

export default defineConfig({
  testDir: "tests/e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: WEB, trace: "retain-on-failure", ...devices["Desktop Chrome"] },
  webServer: [
    {
      command: `uv run python ../../scripts/mock_oidc.py --port 9400 --client web:${CLIENT_SECRET}:${WEB}/auth/callback`,
      cwd: "../api",
      url: `${ISSUER}/.well-known/openid-configuration`,
      reuseExistingServer: false,
    },
    {
      command: `uv run uvicorn --app-dir src --factory ${PACKAGE}.api.app:create_app --host 127.0.0.1 --port 8100`,
      cwd: "../api",
      url: `${API}/health`,
      reuseExistingServer: false,
      env: {
        APP_ENV: "test",
        APP_BUILD_SHA: "e2e",
        APP_DATABASE_URL: DATABASE,
        APP_AUTH_JWKS_FILE: ".dev-keys/jwks.json",
        APP_AUTH_ISSUER: ISSUER,
        APP_AUTH_AUDIENCE: "app-api",
      },
    },
    {
      // The standalone server listens on PORT and HOSTNAME and changes into its own folder, so files are absolute.
      command: "pnpm start",
      url: WEB,
      reuseExistingServer: false,
      env: {
        PORT: "3100",
        HOSTNAME: "127.0.0.1",
        API_URL: API,
        OIDC_ISSUER: ISSUER,
        OIDC_CLIENT_ID: "web",
        OIDC_CLIENT_SECRET: CLIENT_SECRET,
        SESSION_SECRET: "e2e-session-secret-at-least-32-characters-long",
        APP_BASE_URL: WEB,
        APP_CATALOGUE: "1",
      },
    },
  ],
});
