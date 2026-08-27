'use client';

import { authedFetch } from '@/lib/authedFetch';
import type { BulkActionResponse } from '@/types/api';

export async function bulkUpdateConversations(
  ids: string[],
  patch: Record<string, unknown>,
): Promise<BulkActionResponse> {
  return authedFetch<BulkActionResponse>('/conversations/bulk-update', {
    method: 'POST',
    json: { ids, patch },
  });
}
