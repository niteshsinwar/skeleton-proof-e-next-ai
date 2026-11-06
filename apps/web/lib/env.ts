// The web server's configuration, parsed once at first use with Zod (13 "Zod at boundaries").
// Missing or malformed values fail closed (02/B7) with the variable's NAME only, never its value.
// Server-only: never import from a client component.
import { z } from "zod";

const Env = z.object({
  API_URL: z.url(),
  OIDC_ISSUER: z.url(),
  OIDC_CLIENT_ID: z.string().min(1),
  OIDC_CLIENT_SECRET: z.string().min(1),
  SESSION_SECRET: z.string().min(32),
  APP_BASE_URL: z.url(),
});

export type Env = z.infer<typeof Env>;

let cached: Env | null = null;

export function parseEnv(source: Record<string, string | undefined>): Env {
  const parsed = Env.safeParse(source);
  if (!parsed.success) {
    const names = [...new Set(parsed.error.issues.map((issue) => String(issue.path[0])))].sort();
    throw new Error(`Invalid web configuration: ${names.join(", ")}`);
  }
  return parsed.data;
}

export function env(): Env {
  cached ??= parseEnv(process.env);
  return cached;
}

/** The web app's own origin, from configuration: never from Host headers a caller could set. */
export function baseUrl(): string {
  return env().APP_BASE_URL;
}
