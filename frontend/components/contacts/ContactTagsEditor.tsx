'use client';

import { useCallback, useEffect, useState } from 'react';
import { X } from 'lucide-react';
import type { TagResponse, TagWithUsage } from '@/types/api';
import {
  addContactTag,
  getContactTags,
  listTags,
  removeContactTag,
} from '@/lib/tags';

/** Read-only colored tag chip. Reused in the contacts table and the editor. */
export function TagChip({
  tag,
  onRemove,
}: {
  tag: Pick<TagResponse, 'id' | 'name' | 'color'>;
  onRemove?: () => void;
}) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs">
      <span
        className="inline-block h-2.5 w-2.5 rounded-sm border"
        style={{ backgroundColor: tag.color ?? '#e5e7eb' }}
      />
      <span className="truncate">{tag.name}</span>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remove tag ${tag.name}`}
          className="-mr-0.5 rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </span>
  );
}

interface ContactTagsEditorProps {
  contactId: string;
  /** Called after a successful add/remove so parents can refresh their view. */
  onChange?: () => void;
}

/**
 * Manage the tags applied to a contact: shows current tags as removable chips
 * plus a dropdown to attach any saved tag not already applied. Resolves
 * tag_id → name/color locally from the full tag list, so no per-tag fetch.
 */
export function ContactTagsEditor({
  contactId,
  onChange,
}: ContactTagsEditorProps) {
  const [allTags, setAllTags] = useState<TagWithUsage[]>([]);
  const [tagIds, setTagIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [tags, links] = await Promise.all([
        listTags(),
        getContactTags(contactId),
      ]);
      setAllTags(tags);
      setTagIds(links.map((l) => l.tag_id));
    } catch {
      setError('Failed to load tags.');
    } finally {
      setLoading(false);
    }
  }, [contactId]);

  useEffect(() => {
    load();
  }, [load]);

  async function add(tagId: string) {
    if (!tagId) return;
    setBusy(true);
    setError(null);
    try {
      await addContactTag(contactId, tagId);
      setTagIds((prev) => (prev.includes(tagId) ? prev : [...prev, tagId]));
      onChange?.();
    } catch {
      setError('Failed to add tag.');
    } finally {
      setBusy(false);
    }
  }

  async function remove(tagId: string) {
    setBusy(true);
    setError(null);
    try {
      await removeContactTag(contactId, tagId);
      setTagIds((prev) => prev.filter((id) => id !== tagId));
      onChange?.();
    } catch {
      setError('Failed to remove tag.');
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return <p className="text-xs text-muted-foreground">Loading tags…</p>;
  }

  const byId = new Map(allTags.map((t) => [t.id, t]));
  const applied = tagIds
    .map((id) => byId.get(id))
    .filter((t): t is TagWithUsage => Boolean(t));
  const available = allTags.filter((t) => !tagIds.includes(t.id));

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {applied.length === 0 ? (
          <span className="text-xs text-muted-foreground">No tags yet.</span>
        ) : (
          applied.map((t) => (
            <TagChip key={t.id} tag={t} onRemove={() => !busy && remove(t.id)} />
          ))
        )}
      </div>
      <select
        value=""
        disabled={busy || available.length === 0}
        onChange={(e) => add(e.target.value)}
        className="rounded-md border px-2 py-1.5 text-sm outline-none focus:border-primary disabled:opacity-50"
      >
        <option value="" disabled>
          {available.length === 0 ? 'All tags applied' : '+ Add tag…'}
        </option>
        {available.map((t) => (
          <option key={t.id} value={t.id}>
            {t.name}
          </option>
        ))}
      </select>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}
