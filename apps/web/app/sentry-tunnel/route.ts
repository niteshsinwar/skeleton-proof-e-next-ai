// Browser events reach Sentry through this same-origin route, so the CSP keeps connect-src 'self' (03/F38).
export { POST } from "@sentry/nextjs/tunnel";
