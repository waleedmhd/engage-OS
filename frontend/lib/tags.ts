/**
 * Tag + contact-tag API helpers. All calls go through authedFetch.
 */

import { authedFetch } from '@/lib/authedFetch';
import type {
  ContactTagResponse,
  TagListResponse,
  TagWithUsage,
} from '@/types/api';

/** Load all saved tags (the taxonomy managed in Settings). */
export async function listTags(): Promise<TagWithUsage[]> {
  const res = await authedFetch<TagListResponse>('/categorization/tags?limit=500&offset=0');
  return res.items;
}

/** The tags currently applied to a contact (links carry tag_id only). */
export async function getContactTags(
  contactId: string,
): Promise<ContactTagResponse[]> {
  return authedFetch<ContactTagResponse[]>(`/categorization/contacts/${contactId}/tags`);
}

/** Manually attach a saved tag to a contact (idempotent server-side). */
export async function addContactTag(
  contactId: string,
  tagId: string,
): Promise<void> {
  await authedFetch(`/categorization/contacts/${contactId}/tags/${tagId}`, { method: 'POST' });
}

/** Detach a tag from a contact (idempotent server-side). */
export async function removeContactTag(
  contactId: string,
  tagId: string,
): Promise<void> {
  await authedFetch(`/categorization/contacts/${contactId}/tags/${tagId}`, {
    method: 'DELETE',
  });
}
