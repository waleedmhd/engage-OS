/**
 * Token storage for the EngageOS frontend.
 *
 * Access token lives in localStorage (JS reads) AND a JS-readable cookie so
 * Next.js middleware (Edge runtime, no localStorage) can inspect auth state
 * without an API round-trip. Refresh token is localStorage-only.
 */

import { apiFetch } from '@/lib/api';
import type { AuthTokens } from '@/types/api';

const ACCESS_KEY = 'access_token';
const REFRESH_KEY = 'refresh_token';
const COOKIE_NAME = 'access_token';

export function getAccessToken(): string | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem(REFRESH_KEY);
}

export function setTokens(access: string, refresh: string): void {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(ACCESS_KEY, access);
  window.localStorage.setItem(REFRESH_KEY, refresh);
  // Not httpOnly on purpose: middleware + JS both need to read it.
  // max-age matches the backend JWT lifetime (JWT_EXPIRE_MINUTES=60) so the
  // cookie cannot outlive the token and strand returning users off /login.
  document.cookie = `${COOKIE_NAME}=${encodeURIComponent(access)}; path=/; SameSite=Lax; max-age=3600`;
}

export function clearTokens(): void {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(ACCESS_KEY);
  window.localStorage.removeItem(REFRESH_KEY);
  document.cookie = `${COOKIE_NAME}=; path=/; SameSite=Lax; max-age=0`;
}

/**
 * Exchange the stored refresh token for a fresh pair. Returns false (and
 * clears storage) if there is no refresh token or the call fails.
 */
export async function refreshTokens(): Promise<boolean> {
  const refresh = getRefreshToken();
  if (!refresh) {
    clearTokens();
    return false;
  }
  try {
    const tokens = await apiFetch<AuthTokens>('/auth/refresh', {
      method: 'POST',
      json: { refresh_token: refresh },
    });
    setTokens(tokens.access_token, tokens.refresh_token);
    return true;
  } catch {
    clearTokens();
    return false;
  }
}
