import next from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

// Next.js presets plus the frontend rule's hard bans (03/F11, F13): no inline styles anywhere.
const config = [
  ...next,
  ...nextTs,
  {
    rules: {
      "react/forbid-dom-props": ["error", { forbid: ["style"] }],
      "react/forbid-component-props": ["error", { forbid: ["style"] }],
      "@typescript-eslint/no-explicit-any": "error",
      // Every on-screen word comes from lib/labels.ts (03/F16, F55). Props are covered by a source test instead,
      // because this rule's prop option would also flag className, href and type.
      "react/jsx-no-literals": ["error", { noStrings: true, ignoreProps: true }],
    },
  },
  {
    // Exempt by name, with the reason (10/H5, scripts rule): the catalogue's words are samples that show each
    // primitive in each state, not product copy, and the route is off unless APP_CATALOGUE=1 (B3-4); test files
    // hold fixtures, not screen copy.
    files: ["components/catalogue.tsx", "components/ai/catalogue-ai.tsx", "tests/**"],
    rules: { "react/jsx-no-literals": "off" },
  },
  { ignores: [".next/**", "lib/api/generated/**", "test-results/**", "playwright-report/**", "next-env.d.ts"] },
];

export default config;
