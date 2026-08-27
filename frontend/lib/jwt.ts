/**
 * Edge-safe access-token validity check.
 *
 * The middleware auth gate must reject a token whose JWT `exp` has passed,
 * not merely check that a cookie exists — otherwise the login cookie
 * (which outlives the JWT) traps returning users off /login.
 *
 * No signature verification: that's the API's job. This only decides whether
 * the edge should treat the request as logged-in for routing.
 */

function decodeBase64Url(segment: string): string | null {
  try {
    const pad = segment.length % 4 === 0 ? '' : '='.repeat(4 - (segment.length % 4));
    const base64 = segment.replace(/-/g, '+').replace(/_/g, '/') + pad;
    return atob(base64);
  } catch {
    return null;
  }
}

export function isJwtValid(token: string | null | undefined): boolean {
  if (!token) return false;
  const parts = token.split('.');
  if (parts.length !== 3) return false;

  const json = decodeBase64Url(parts[1]);
  if (!json) return false;

  let payload: { exp?: unknown };
  try {
    payload = JSON.parse(json);
  } catch {
    return false;
  }

  if (typeof payload.exp !== 'number') return false;
  return payload.exp * 1000 > Date.now();
}
