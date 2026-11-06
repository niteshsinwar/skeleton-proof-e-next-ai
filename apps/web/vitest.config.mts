import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The include pattern is every test file, never a list of the folders that exist today (03/F23).
// Vite resolves the tsconfig `@/*` paths itself, so no paths plugin is needed (03/F51).
export default defineConfig({
  plugins: [react()],
  resolve: { tsconfigPaths: true },
  test: {
    environment: "jsdom",
    include: ["**/*.test.{ts,tsx}"],
    exclude: ["node_modules/**", ".next/**", "dist/**", "tests/e2e/**"],
  },
});
