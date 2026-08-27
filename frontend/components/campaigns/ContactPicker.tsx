'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Filter, Search, X } from 'lucide-react';
import { fetchPage } from '@/lib/lists';
import { listTags } from '@/lib/tags';
import { Spinner } from '@/components/shared/ui';
import type { ContactResponse, ContactStatus, TagWithUsage } from '@/types/api';

const PAGE_SIZE = 10;

const STATUS_OPTIONS: ContactStatus[] = [
  'active',
  'inactive',
  'contacted',
  'follow_up',
  'interested',
  'not_interested',
];

interface ContactPickerProps {
  selectedIds: Set<string>;
  onSelectionChange: (ids: Set<string>) => void;
}

export default function ContactPicker({
  selectedIds,
  onSelectionChange,
}: ContactPickerProps) {
  const [contacts, setContacts] = useState<ContactResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  const [loading, setLoading] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const [filterTagId, setFilterTagId] = useState('');
  const [filterStatuses, setFilterStatuses] = useState<Set<ContactStatus>>(new Set());
  const [tags, setTags] = useState<TagWithUsage[]>([]);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    listTags().then(setTags).catch(() => setTags([]));
  }, []);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      setDebouncedQ(q);
      setPage(1);
    }, 300);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [q]);

  const fetchContacts = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
      });
      if (debouncedQ) params.set('q', debouncedQ);
      if (filterTagId) params.set('tag_id', filterTagId);
      if (filterStatuses.size > 0) {
        params.set('status', Array.from(filterStatuses).join(','));
      }
      const res = await fetchPage<ContactResponse>(
        `/contacts?${params.toString()}`,
      );
      setContacts(res.items);
      setTotal(res.total);
    } catch {
      setContacts([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, debouncedQ, filterTagId, filterStatuses]);

  useEffect(() => {
    fetchContacts();
  }, [fetchContacts]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  function toggle(id: string) {
    const next = new Set(selectedIds);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    onSelectionChange(next);
  }

  function clearAll() {
    onSelectionChange(new Set());
  }

  function toggleStatus(s: ContactStatus) {
    const next = new Set(filterStatuses);
    if (next.has(s)) next.delete(s);
    else next.add(s);
    setFilterStatuses(next);
    setPage(1);
  }

  function clearFilters() {
    setFilterTagId('');
    setFilterStatuses(new Set());
    setPage(1);
  }

  const hasFilters = filterTagId !== '' || filterStatuses.size > 0;
  const selectedOnPage = contacts.filter((c) => selectedIds.has(c.id)).length;

  return (
    <div className="space-y-2 rounded-md border p-3">
      {/* Search */}
      <div className="relative">
        <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-muted-foreground" />
        <input
          type="text"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search contacts..."
          className="w-full rounded-md border py-1.5 pl-8 pr-3 text-xs"
        />
      </div>

      {/* Filter toggle */}
      <button
        type="button"
        onClick={() => setShowFilters(!showFilters)}
        className={clsx(
          'flex items-center gap-1 text-xs',
          hasFilters ? 'text-primary font-medium' : 'text-muted-foreground',
        )}
      >
        <Filter className="h-3 w-3" />
        Filters
        {hasFilters && (
          <span className="rounded-full bg-primary px-1.5 py-0 text-[10px] text-primary-foreground">
            {(filterTagId ? 1 : 0) + filterStatuses.size}
          </span>
        )}
      </button>

      {/* Filter bar */}
      {showFilters && (
        <div className="space-y-2 rounded border p-2 text-xs">
          {/* Tag filter */}
          <div>
            <label className="mb-0.5 block text-muted-foreground">Tag</label>
            <select
              value={filterTagId}
              onChange={(e) => {
                setFilterTagId(e.target.value);
                setPage(1);
              }}
              className="w-full rounded border px-2 py-1 text-xs"
            >
              <option value="">All tags</option>
              {tags.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} ({t.usage_count})
                </option>
              ))}
            </select>
          </div>

          {/* Status filter */}
          <div>
            <label className="mb-0.5 block text-muted-foreground">Status</label>
            <div className="flex flex-wrap gap-x-2 gap-y-0.5">
              {STATUS_OPTIONS.map((s) => (
                <label key={s} className="flex items-center gap-1 capitalize">
                  <input
                    type="checkbox"
                    checked={filterStatuses.has(s)}
                    onChange={() => toggleStatus(s)}
                    className="h-3 w-3"
                  />
                  {s.replace('_', ' ')}
                </label>
              ))}
            </div>
          </div>

          {hasFilters && (
            <button
              type="button"
              onClick={clearFilters}
              className="text-muted-foreground hover:underline"
            >
              Clear all filters
            </button>
          )}
        </div>
      )}

      {/* Selection summary */}
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          {selectedIds.size} contact{selectedIds.size !== 1 ? 's' : ''} selected
        </span>
        {selectedIds.size > 0 && (
          <button
            type="button"
            onClick={clearAll}
            className="flex items-center gap-1 text-red-600 hover:underline"
          >
            <X className="h-3 w-3" /> Clear all
          </button>
        )}
      </div>

      {/* Contact list */}
      <div className="max-h-48 space-y-0.5 overflow-y-auto">
        {loading ? (
          <div className="flex justify-center py-4">
            <Spinner />
          </div>
        ) : contacts.length === 0 ? (
          <p className="py-4 text-center text-xs text-muted-foreground">
            {debouncedQ || hasFilters
              ? 'No matching contacts'
              : 'No contacts found'}
          </p>
        ) : (
          contacts.map((c) => (
            <label
              key={c.id}
              className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 hover:bg-muted"
            >
              <input
                type="checkbox"
                checked={selectedIds.has(c.id)}
                onChange={() => toggle(c.id)}
                className="h-3.5 w-3.5"
              />
              <span className="flex-1 truncate text-xs">
                {c.name || c.phone}
                {c.name && (
                  <span className="ml-1.5 text-muted-foreground">{c.phone}</span>
                )}
              </span>
            </label>
          ))
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs">
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
            className="rounded border px-2 py-0.5 hover:bg-muted disabled:opacity-40"
          >
            Prev
          </button>
          <span className="text-muted-foreground">
            Page {page} of {totalPages}
          </span>
          <button
            type="button"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
            className="rounded border px-2 py-0.5 hover:bg-muted disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}

      {/* Hint about selected contacts across pages */}
      {selectedOnPage < selectedIds.size && selectedIds.size > 0 && (
        <p className="text-[10px] text-muted-foreground">
          {selectedIds.size - selectedOnPage} selected contact
          {selectedIds.size - selectedOnPage !== 1 ? 's' : ''} on other pages
        </p>
      )}
    </div>
  );
}

function clsx(...args: (string | false | undefined | null)[]): string {
  return args.filter(Boolean).join(' ');
}
