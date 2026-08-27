'use client';

import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { PageHeader } from '@/components/shared/PageHeader';
import { EmptyState } from '@/components/shared/EmptyState';
import { ErrorBox, SkeletonRows } from '@/components/shared/ui';
import { authedFetch } from '@/lib/authedFetch';
import { fetchArray, fetchPage } from '@/lib/lists';
import type {
  ContactResponse,
  TagSuggestionResponse,
  TagSuggestionStatus,
  TagWithUsage,
} from '@/types/api';

const TABS: TagSuggestionStatus[] = ['pending', 'approved', 'rejected'];
const PAGE_SIZE = 50;

type TagInfo = { name: string; color: string | null };

export default function TagReviewPage() {
  // useSearchParams() forces dynamic rendering; wrap in Suspense so the
  // Next.js prerender can statically generate the surrounding shell.
  return (
    <Suspense fallback={<SkeletonRows rows={6} />}>
      <TagReviewInner />
    </Suspense>
  );
}

function TagReviewInner() {
  const params = useSearchParams();
  const contactFilter = params.get('contact_id') ?? null;

  const [tab, setTab] = useState<TagSuggestionStatus>('pending');
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<TagSuggestionResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [tags, setTags] = useState<Record<string, TagInfo>>({});
  const [contacts, setContacts] = useState<Record<string, ContactResponse>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const queryString = useMemo(() => {
    const q = new URLSearchParams({
      status: tab,
      page: String(page),
      page_size: String(PAGE_SIZE),
    });
    if (contactFilter) q.set('contact_id', contactFilter);
    return q.toString();
  }, [tab, page, contactFilter]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [sugg, tagList] = await Promise.all([
        fetchPage<TagSuggestionResponse>(`/categorization/tag-suggestions?${queryString}`),
        fetchArray<TagWithUsage>('/categorization/tags?limit=500&offset=0'),
      ]);
      setItems(sugg.items);
      setTotal(sugg.total);
      setTags(
        Object.fromEntries(
          tagList.map((t) => [t.id, { name: t.name, color: t.color ?? null }]),
        ),
      );

      const uniqueContactIds = Array.from(new Set(sugg.items.map((s) => s.contact_id)));
      const fetched = await Promise.all(
        uniqueContactIds.map((id) =>
          authedFetch<ContactResponse>(`/contacts/${id}`).catch(() => null),
        ),
      );
      const map: Record<string, ContactResponse> = {};
      uniqueContactIds.forEach((id, i) => {
        const c = fetched[i];
        if (c) map[id] = c;
      });
      setContacts(map);
    } catch {
      setError('Failed to load tag suggestions.');
    } finally {
      setLoading(false);
    }
  }, [queryString]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  async function review(id: string, action: 'approve' | 'reject') {
    setBusyId(id);
    const prev = items;
    setItems((cur) => cur.filter((s) => s.id !== id));
    try {
      await authedFetch(`/tag-suggestions/${id}/${action}`, {
        method: 'POST',
        json: {},
      });
    } catch {
      setItems(prev);
      setError('Action failed.');
    } finally {
      setBusyId(null);
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Tag Review"
        description={
          contactFilter
            ? `AI-suggested contact tags awaiting review — filtered to contact ${contactFilter.slice(0, 8)}…`
            : 'AI-suggested contact tags awaiting agent approval.'
        }
      />

      <div className="flex gap-1 border-b">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => {
              setTab(t);
              setPage(1);
            }}
            className={`px-4 py-2 text-sm font-medium capitalize ${
              tab === t
                ? 'border-b-2 border-primary text-primary'
                : 'text-muted-foreground'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {loading ? (
        <SkeletonRows rows={6} />
      ) : error ? (
        <ErrorBox message={error} onRetry={fetchData} />
      ) : items.length === 0 ? (
        <EmptyState
          title="Nothing to review"
          description={`No ${tab} tag suggestions.`}
        />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            {items.map((s) => {
              const tagInfo = tags[s.tag_id];
              const contact = contacts[s.contact_id];
              return (
                <div key={s.id} className="rounded-lg border bg-white p-4">
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2 text-sm font-medium">
                        <span
                          className="inline-block h-3 w-3 rounded-sm border"
                          style={{ backgroundColor: tagInfo?.color ?? '#e5e7eb' }}
                        />
                        <span>Tag: {tagInfo?.name ?? s.tag_id}</span>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {contact ? (
                          <Link
                            href={`/contacts/${s.contact_id}`}
                            className="hover:underline"
                          >
                            {contact.name ?? contact.phone ?? s.contact_id}
                          </Link>
                        ) : (
                          <span>{s.contact_id}</span>
                        )}
                      </p>
                    </div>
                    {typeof s.confidence === 'number' ? (
                      <span className="rounded-full bg-muted px-2 py-0.5 text-xs">
                        {Math.round(s.confidence * 100)}%
                      </span>
                    ) : null}
                  </div>
                  {s.reason ? (
                    <p className="mt-2 text-sm text-muted-foreground">{s.reason}</p>
                  ) : null}
                  {tab === 'pending' ? (
                    <div className="mt-4 flex gap-2">
                      <button
                        disabled={busyId === s.id}
                        onClick={() => review(s.id, 'approve')}
                        className="rounded-md bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
                      >
                        Approve
                      </button>
                      <button
                        disabled={busyId === s.id}
                        onClick={() => review(s.id, 'reject')}
                        className="rounded-md bg-red-600 px-3 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
                      >
                        Reject
                      </button>
                    </div>
                  ) : (
                    <p className="mt-3 text-xs capitalize text-muted-foreground">
                      {s.status}
                      {s.reviewed_at
                        ? ` · ${new Date(s.reviewed_at).toLocaleDateString()}`
                        : ''}
                    </p>
                  )}
                </div>
              );
            })}
          </div>

          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              Page {page} of {totalPages} · {total} total
            </span>
            <div className="flex gap-2">
              <button
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="rounded-md border px-3 py-1 disabled:opacity-50"
              >
                Prev
              </button>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
                className="rounded-md border px-3 py-1 disabled:opacity-50"
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
