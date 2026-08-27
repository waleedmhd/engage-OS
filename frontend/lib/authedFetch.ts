/**
 * Authenticated fetch wrapper. Injects the stored access token, transparently
 * refreshes once on 401, and bounces to /login if refresh fails.
 *
 * All page data calls go through this — never apiFetch directly.
 */

import { apiFetch, type ApiInit } from '@/lib/api';
import { clearTokens, getAccessToken, refreshTokens } from '@/lib/auth';

type FetchError = Error & { status?: number; payload?: unknown };

function isStatus(err: unknown, status: number): boolean {
  return Boolean(err) && (err as FetchError).status === status;
}

function redirectToLogin(): void {
  clearTokens();
  if (typeof window !== 'undefined') {
    window.location.href = '/login';
  }
}

export async function authedFetch<T = unknown>(
  path: string,
  init: ApiInit = {},
): Promise<T> {
  try {
    return await apiFetch<T>(path, { ...init, token: getAccessToken() });
  } catch (err) {
    if (isStatus(err, 401)) {
      const refreshed = await refreshTokens();
      if (refreshed) {
        try {
          return await apiFetch<T>(path, { ...init, token: getAccessToken() });
        } catch (retryErr) {
          if (isStatus(retryErr, 401)) {
            redirectToLogin();
          }
          throw retryErr;
        }
      }
      redirectToLogin();
    }
    throw err;
  }
}
