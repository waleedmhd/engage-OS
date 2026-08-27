/**
 * Defensive list fetchers.
 *
 * The backend's list endpoints are not uniform: some return a bare JSON array
 * (e.g. GET /categorization/tags historically), others a paginated object such as
 * `{ items, total, ... }`. A component that assumes the wrong shape and calls
 * `.map` on it crashes the whole view — that's the "C.map is not a function"
 * class of bug (the New Campaign modal cast a paginated `/categorization/tags`
 * response to an array). Routing list fetches through these helpers normalizes
 * either shape
 * into a guaranteed array, so a future backend/frontend shape drift degrades to
 * an empty list instead of a runtime crash.
 */

import type { ApiInit } from '@/lib/api';
import { authedFetch } from '@/lib/authedFetch';

/** Pull an array out of either a bare array or a `{ items: [...] }` envelope. */
function extractItems<T>(body: unknown): T[] {
  if (Array.isArray(body)) return body as T[];
  if (
    body &&
    typeof body === 'object' &&
    Array.isArray((body as { items?: unknown }).items)
  ) {
    return (body as { items: T[] }).items;
  }
  return [];
}

function extractTotal(body: unknown, fallback: number): number {
  if (body && typeof body === 'object') {
    const total = (body as { total?: unknown }).total;
    if (typeof total === 'number') return total;
  }
  return fallback;
}

/**
 * Fetch a list endpoint and always return an array, whether the endpoint sends
 * a bare array or a `{ items }` envelope. Network/auth errors still throw (so
 * callers can show an error state); only an unexpected *shape* degrades to `[]`.
 */
export async function fetchArray<T>(
  path: string,
  init: ApiInit = {},
): Promise<T[]> {
  return extractItems<T>(await authedFetch<unknown>(path, init));
}

/**
 * Fetch a paginated endpoint and always return a well-formed `{ items, total }`,
 * normalizing a bare-array response (items = the array, total = its length) or a
 * malformed body (`{ items: [], total: 0 }`).
 */
export async function fetchPage<T>(
  path: string,
  init: ApiInit = {},
): Promise<{ items: T[]; total: number }> {
  const body = await authedFetch<unknown>(path, init);
  const items = extractItems<T>(body);
  return { items, total: extractTotal(body, items.length) };
}
