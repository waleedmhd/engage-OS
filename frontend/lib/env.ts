/**
 * Client-accessible env vars for EngageOS.
 *
 * NEXT_PUBLIC_* vars must be accessed as literal property reads
 * (process.env.NEXT_PUBLIC_FOO, not process.env[name]) so that
 * Next.js can inline them at build time into the client bundle.
 * Dynamic access breaks the static replacement and produces undefined.
 */

export const env = {
  apiUrl: process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1',
  wsUrl: process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000/ws',
};
