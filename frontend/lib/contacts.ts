'use client';

import { authedFetch } from '@/lib/authedFetch';
import { fetchArray } from '@/lib/lists';
import type {
  BulkActionResponse,
  BulkDeleteRequest,
  BulkUpdateRequest,
  ContactCreateRequest,
  ContactResponse,
  ContactUpdateRequest,
  UserResponse,
} from '@/types/api';

export async function listUsers(): Promise<UserResponse[]> {
  return fetchArray<UserResponse>('/users?limit=200');
}

export async function createContact(
  req: ContactCreateRequest,
): Promise<ContactResponse> {
  return authedFetch<ContactResponse>('/contacts', {
    method: 'POST',
    json: req,
  });
}

export async function bulkUpdateContacts(
  req: BulkUpdateRequest,
): Promise<BulkActionResponse> {
  return authedFetch<BulkActionResponse>('/contacts/bulk-update', {
    method: 'POST',
    json: req,
  });
}

export async function updateContact(
  id: string,
  req: ContactUpdateRequest,
): Promise<ContactResponse> {
  return authedFetch<ContactResponse>(`/contacts/${id}`, {
    method: 'PATCH',
    json: req,
  });
}

export async function bulkDeleteContacts(
  ids: string[],
): Promise<BulkActionResponse> {
  const req: BulkDeleteRequest = { ids };
  return authedFetch<BulkActionResponse>('/contacts/bulk-delete', {
    method: 'POST',
    json: req,
  });
}
