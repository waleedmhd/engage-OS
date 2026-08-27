/**
 * Typed fetch wrapper for the EngageOS backend.
 *
 * Phase 0: bare `fetch` with base URL + Authorization header injection. Body
 * shaping and error normalisation arrive with the first feature that needs
 * them.
 */

import { env } from '@/lib/env';

export type ApiInit = RequestInit & {
  token?: string | null;
  json?: unknown;
};

export async function apiFetch<T = unknown>(path: string, init: ApiInit = {}): Promise<T> {
  const { token, json, headers, body, ...rest } = init;

  const finalHeaders = new Headers(headers ?? {});
  if (token) finalHeaders.set('Authorization', `Bearer ${token}`);
  let finalBody: BodyInit | undefined = body as BodyInit | undefined;
  if (json !== undefined) {
    finalHeaders.set('Content-Type', 'application/json');
    finalBody = JSON.stringify(json);
  }

  const url = path.startsWith('http') ? path : `${env.apiUrl}${path}`;
  const response = await fetch(url, { ...rest, headers: finalHeaders, body: finalBody });

  const text = await response.text();
  const payload = text ? (JSON.parse(text) as unknown) : undefined;

  if (!response.ok) {
    const error = new Error(`Request failed: ${response.status}`);
    (error as Error & { status: number; payload: unknown }).status = response.status;
    (error as Error & { status: number; payload: unknown }).payload = payload;
    throw error;
  }

  return payload as T;
}
