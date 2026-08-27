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
  CampaignCategoryCreateRequest,
  CampaignCategoryResponse,
  CampaignCategoryUpdateRequest,
  CampaignCategoryWithUsage,
} from '@/types/api';

const PAGE_SIZE = 100;

type FetchError = Error & { status?: number; payload?: unknown };

function friendlyError(err: unknown, fallback: string): string {
  const e = err as FetchError;
  const payload = e?.payload as
    | {
        error?: {
          message?: string;
          details?: { campaigns?: number };
        };
        detail?: string | { campaigns?: number };
        message?: string;
      }
    | undefined;
  const details =
    payload?.error?.details ??
    (typeof payload?.detail === 'object' ? payload.detail : undefined);
  if (details && (details.campaigns ?? 0) > 0) {
    const c = details.campaigns ?? 0;
    return `Cannot delete — used by ${c} campaign(s). Reassign or remove them first.`;
  }
  const msg =
    payload?.error?.message ??
    (typeof payload?.detail === 'string' ? payload.detail : undefined) ??
    payload?.message;
  if (msg?.includes('campaign_category_in_use'))
    return 'Cannot delete — category is in use. Reassign or remove the campaigns first.';
  if (msg?.includes('campaign_category_name_taken'))
    return 'A category with that name already exists.';
  if (msg?.includes('no_changes')) return 'No fields were changed.';
  return msg ?? e?.message ?? fallback;
}

type FormState = { name: string; description: string; color: string };
const EMPTY_FORM: FormState = { name: '', description: '', color: '#888888' };

export default function CampaignCategoriesAdminPage() {
  const { user, isLoading: authLoading } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [items, setItems] = useState<CampaignCategoryWithUsage[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<CampaignCategoryWithUsage | null>(null);
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
      const body = await fetchPage<CampaignCategoryWithUsage>(
        `/campaign-categories?${search}`,
      );
      setItems(body.items);
      setTotal(body.total);
    } catch (err) {
      setError(friendlyError(err, 'Failed to load campaign categories.'));
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

  function openEdit(c: CampaignCategoryWithUsage) {
    setEditing(c);
    setForm({
      name: c.name,
      description: c.description ?? '',
      color: c.color ?? '#888888',
    });
    setShowForm(true);
  }

  async function submitForm(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      if (editing) {
        const body: CampaignCategoryUpdateRequest = {};
        if (form.name !== editing.name) body.name = form.name;
        if (form.description !== (editing.description ?? ''))
          body.description = form.description || null;
        if (form.color !== (editing.color ?? '#888888'))
          body.color = form.color;
        await authedFetch<CampaignCategoryResponse>(
          `/campaign-categories/${editing.id}`,
          { method: 'PATCH', json: body },
        );
      } else {
        const payload: CampaignCategoryCreateRequest = {
          name: form.name,
          description: form.description || null,
          color: form.color || null,
        };
        await authedFetch<CampaignCategoryResponse>('/campaign-categories', {
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

  async function remove(c: CampaignCategoryWithUsage) {
    if (!confirm(`Delete campaign category "${c.name}"?`)) return;
    setError(null);
    try {
      await authedFetch(`/campaign-categories/${c.id}`, { method: 'DELETE' });
      await fetchData();
    } catch (err) {
      setError(friendlyError(err, 'Delete failed.'));
    }
  }

  if (authLoading) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Campaign Categories"
          description="Manage the campaign taxonomy used for organization and reporting."
        />
        <SkeletonRows rows={6} />
      </div>
    );
  }
  if (!isAdmin) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Campaign Categories"
          description="Manage the campaign taxonomy used for organization and reporting."
        />
        <PermissionState title="Admins only" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Campaign Categories"
        description="Manage the campaign taxonomy used for organization and reporting."
      />

      <div className="flex items-center justify-between gap-3">
        <input
          type="search"
          placeholder="Search categories…"
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
          <Plus className="h-4 w-4" /> New category
        </button>
      </div>

      {error ? <ErrorBox message={error} onRetry={fetchData} /> : null}

      {loading ? (
        <SkeletonRows rows={6} />
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No categories.</p>
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
            {items.map((c) => (
              <tr key={c.id} className="border-t">
                <td className="py-2">
                  <span className="inline-flex items-center gap-2">
                    <span
                      className="inline-block h-3 w-3 rounded-sm border"
                      style={{ backgroundColor: c.color ?? '#e5e7eb' }}
                    />
                    {c.name}
                  </span>
                </td>
                <td className="py-2 text-muted-foreground">
                  {c.description ?? '—'}
                </td>
                <td className="py-2">{c.usage_count}</td>
                <td className="py-2 text-right">
                  <button
                    onClick={() => openEdit(c)}
                    className="mr-2 text-muted-foreground hover:text-foreground"
                    aria-label="Edit"
                  >
                    <Pencil className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => remove(c)}
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
          {total === 0
            ? '0'
            : `${offset + 1}–${Math.min(offset + items.length, total)}`}{' '}
          of {total}
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
              {editing ? `Edit "${editing.name}"` : 'Create category'}
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
