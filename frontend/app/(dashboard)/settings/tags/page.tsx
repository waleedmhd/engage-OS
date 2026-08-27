'use client';

import { useCallback, useEffect, useState } from 'react';
import { Pencil, Plus, Trash2 } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import {
  ErrorBox,
  PermissionState,
  SkeletonRows,
  Spinner,
} from '@/components/shared/ui';
import { authedFetch } from '@/lib/authedFetch';
import { fetchPage } from '@/lib/lists';
import { useAuth } from '@/hooks/useAuth';
import type {
  TagCreateRequest,
  TagResponse,
  TagUpdateRequest,
  TagWithUsage,
} from '@/types/api';

const PAGE_SIZE = 100;

type FetchError = Error & { status?: number; payload?: unknown };

function friendlyError(err: unknown, fallback: string): string {
  const e = err as FetchError;
  const payload = e?.payload as
    | {
        error?: {
          message?: string;
          details?: { contacts?: number; suggestions?: number };
        };
        detail?: string | { contacts?: number; suggestions?: number };
        message?: string;
      }
    | undefined;
  const details = payload?.error?.details ?? (typeof payload?.detail === 'object' ? payload.detail : undefined);
  if (details && (details.contacts ?? 0) > 0 || (details && (details.suggestions ?? 0) > 0)) {
    const c = details?.contacts ?? 0;
    const s = details?.suggestions ?? 0;
    return `Cannot delete — used by ${c} contact(s), ${s} pending suggestion(s). Remove usages first.`;
  }
  const msg = payload?.error?.message ?? (typeof payload?.detail === 'string' ? payload.detail : undefined) ?? payload?.message;
  if (msg?.includes('tag_in_use'))
    return 'Cannot delete — tag is in use. Remove its usages first.';
  if (msg?.includes('tag_name_taken'))
    return 'A tag with that name already exists.';
  if (msg?.includes('no_changes')) return 'No fields were changed.';
  return msg ?? e?.message ?? fallback;
}

type FormState = { name: string; description: string; color: string };
const EMPTY_FORM: FormState = { name: '', description: '', color: '#888888' };

export default function TagsAdminPage() {
  const { user, isLoading: authLoading } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [items, setItems] = useState<TagWithUsage[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<TagWithUsage | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const search = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(offset),
      });
      if (q.trim()) search.set('q', q.trim());
      const body = await fetchPage<TagWithUsage>(`/categorization/tags?${search}`);
      setItems(body.items);
      setTotal(body.total);
    } catch (err) {
      setError(friendlyError(err, 'Failed to load tags.'));
    } finally {
      setLoading(false);
    }
  }, [offset, q]);

  useEffect(() => {
    if (!isAdmin) return;
    const id = window.setTimeout(fetchData, q ? 300 : 0);
    return () => window.clearTimeout(id);
  }, [fetchData, isAdmin, q]);

  function openCreate() {
    setEditing(null);
    setForm(EMPTY_FORM);
    setShowForm(true);
  }

  function openEdit(t: TagWithUsage) {
    setEditing(t);
    setForm({
      name: t.name,
      description: t.description ?? '',
      color: t.color ?? '#888888',
    });
    setShowForm(true);
  }

  async function submitForm(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      if (editing) {
        const body: TagUpdateRequest = {};
        if (form.name !== editing.name) body.name = form.name;
        if (form.description !== (editing.description ?? ''))
          body.description = form.description || null;
        if (form.color !== (editing.color ?? '#888888')) body.color = form.color;
        await authedFetch<TagResponse>(`/categorization/tags/${editing.id}`, {
          method: 'PATCH',
          json: body,
        });
      } else {
        const payload: TagCreateRequest = {
          name: form.name,
          description: form.description || null,
          color: form.color || null,
        };
        await authedFetch<TagResponse>('/categorization/tags', {
          method: 'POST',
          json: payload,
        });
      }
      setShowForm(false);
      await fetchData();
    } catch (err) {
      setError(friendlyError(err, 'Save failed.'));
    } finally {
      setSaving(false);
    }
  }

  async function remove(t: TagWithUsage) {
    if (!confirm(`Delete tag "${t.name}"?`)) return;
    setError(null);
    try {
      await authedFetch(`/categorization/tags/${t.id}`, { method: 'DELETE' });
      await fetchData();
    } catch (err) {
      setError(friendlyError(err, 'Delete failed.'));
    }
  }

  if (authLoading) {
    return (
      <div className="space-y-6">
        <PageHeader title="Tags" description="Manage the contact tag taxonomy." />
        <SkeletonRows rows={6} />
      </div>
    );
  }
  if (!isAdmin) {
    return (
      <div className="space-y-6">
        <PageHeader title="Tags" description="Manage the contact tag taxonomy." />
        <PermissionState title="Admins only" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Tags" description="Manage the contact tag taxonomy." />

      <div className="flex items-center justify-between gap-3">
        <input
          type="search"
          placeholder="Search tags…"
          value={q}
          onChange={(e) => {
            setOffset(0);
            setQ(e.target.value);
          }}
          className="w-72 rounded-md border px-3 py-1.5 text-sm"
        />
        <button
          onClick={openCreate}
          className="inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-white"
        >
          <Plus className="h-4 w-4" /> New tag
        </button>
      </div>

      {error ? <ErrorBox message={error} onRetry={fetchData} /> : null}

      {loading ? (
        <SkeletonRows rows={6} />
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No tags.</p>
      ) : (
        <div className="overflow-x-auto">
        <table className="w-full min-w-[480px] text-sm">
          <thead className="text-left text-xs uppercase text-muted-foreground">
            <tr>
              <th className="py-2">Name</th>
              <th className="py-2">Description</th>
              <th className="py-2">Usage</th>
              <th className="py-2"></th>
            </tr>
          </thead>
          <tbody>
            {items.map((t) => (
              <tr key={t.id} className="border-t">
                <td className="py-2">
                  <span className="inline-flex items-center gap-2">
                    <span
                      className="inline-block h-3 w-3 rounded-sm border"
                      style={{ backgroundColor: t.color ?? '#e5e7eb' }}
                    />
                    {t.name}
                  </span>
                </td>
                <td className="py-2 text-muted-foreground">
                  {t.description ?? '—'}
                </td>
                <td className="py-2">{t.usage_count}</td>
                <td className="py-2 text-right">
                  <button
                    onClick={() => openEdit(t)}
                    className="mr-2 text-muted-foreground hover:text-foreground"
                    aria-label="Edit"
                  >
                    <Pencil className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => remove(t)}
                    className="text-red-600 hover:text-red-700"
                    aria-label="Delete"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}

      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          {total === 0 ? '0' : `${offset + 1}–${Math.min(offset + items.length, total)}`} of {total}
        </span>
        <div className="flex gap-2">
          <button
            disabled={offset === 0}
            onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
            className="rounded-md border px-3 py-1 disabled:opacity-50"
          >
            Prev
          </button>
          <button
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset((o) => o + PAGE_SIZE)}
            className="rounded-md border px-3 py-1 disabled:opacity-50"
          >
            Next
          </button>
        </div>
      </div>

      {showForm ? (
        <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/30">
          <form
            onSubmit={submitForm}
            className="w-full max-w-md space-y-3 rounded-md bg-white p-5 shadow-lg"
          >
            <h3 className="text-base font-semibold">
              {editing ? `Edit "${editing.name}"` : 'Create tag'}
            </h3>
            <div>
              <label className="block text-xs font-medium">Name</label>
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
                className="mt-1 w-full rounded-md border px-2 py-1 text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-medium">Description</label>
              <textarea
                value={form.description}
                onChange={(e) =>
                  setForm({ ...form, description: e.target.value })
                }
                rows={3}
                className="mt-1 w-full rounded-md border px-2 py-1 text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-medium">Color</label>
              <input
                type="color"
                value={form.color}
                onChange={(e) => setForm({ ...form, color: e.target.value })}
                className="mt-1 h-8 w-20 rounded-md border"
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowForm(false)}
                className="rounded-md border px-3 py-1.5 text-sm"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={saving}
                className="inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-sm text-white disabled:opacity-50"
              >
                {saving ? <Spinner /> : null}
                Save
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </div>
  );
}
