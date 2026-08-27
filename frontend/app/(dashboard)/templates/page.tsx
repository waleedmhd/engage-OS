'use client';

import { useCallback, useEffect, useState } from 'react';
import { Download, Plus, RefreshCw, X } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import { ErrorBox, Modal, Pagination, SkeletonRows, Spinner } from '@/components/shared/ui';
import { authedFetch } from '@/lib/authedFetch';
import { fetchPage } from '@/lib/lists';
import { useAuth } from '@/hooks/useAuth';
import type {
  TemplateCategory,
  TemplateImportResult,
  TemplateResponse,
  TemplateSubmitRequest,
} from '@/types/api';

const PAGE_SIZE = 20;
const TABS = ['all', 'pending', 'approved', 'rejected', 'disabled'] as const;
const CATEGORIES: TemplateCategory[] = ['marketing', 'utility', 'authentication'];

function fmt(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
}

const STATUS_STYLES: Record<string, string> = {
  approved: 'bg-green-100 text-green-700',
  pending: 'bg-yellow-100 text-yellow-800',
  rejected: 'bg-red-100 text-red-700',
  disabled: 'bg-gray-100 text-gray-700',
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-medium capitalize ${
        STATUS_STYLES[status] ?? 'bg-gray-100 text-gray-700'
      }`}
    >
      {status}
    </span>
  );
}

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[120px,1fr] gap-x-3 border-b py-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="break-all font-medium">{value}</span>
    </div>
  );
}

export default function TemplatesPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [tab, setTab] = useState<(typeof TABS)[number]>('all');
  const [items, setItems] = useState<TemplateResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Detail sidebar
  const [detail, setDetail] = useState<TemplateResponse | null>(null);

  // Create modal
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState<TemplateSubmitRequest>({
    name: '',
    category: 'utility',
    language: 'en',
    body: '',
  });

  // Per-row sync
  const [busyId, setBusyId] = useState<string | null>(null);

  // Import from Meta
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<TemplateImportResult | null>(null);

  const fetchTemplates = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
      });
      if (tab !== 'all') params.set('status', tab);
      const res = await fetchPage<TemplateResponse>(
        `/templates?${params.toString()}`,
      );
      setItems(res.items);
      setTotal(res.total);
    } catch {
      setError('Failed to load templates.');
    } finally {
      setLoading(false);
    }
  }, [tab, page]);

  useEffect(() => {
    fetchTemplates();
  }, [fetchTemplates]);

  async function submitCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    try {
      await authedFetch<TemplateResponse>('/templates/submit', {
        method: 'POST',
        json: form,
      });
      setShowCreate(false);
      setForm({ name: '', category: 'utility', language: 'en', body: '' });
      await fetchTemplates();
    } catch {
      setError('Failed to submit template.');
    } finally {
      setCreating(false);
    }
  }

  async function sync(id: string) {
    setBusyId(id);
    try {
      const updated = await authedFetch<TemplateResponse>(`/templates/${id}/sync`, {
        method: 'POST',
      });
      // Refresh detail panel if it's open for this template
      if (detail?.id === id) setDetail(updated);
      await fetchTemplates();
    } catch {
      setError('Failed to sync template status.');
    } finally {
      setBusyId(null);
    }
  }

  async function importFromMeta() {
    setImporting(true);
    setImportResult(null);
    try {
      const result = await authedFetch<TemplateImportResult>(
        '/templates/import-from-meta',
        { method: 'POST' },
      );
      setImportResult(result);
      await fetchTemplates();
    } catch {
      setError('Failed to import templates from Meta.');
    } finally {
      setImporting(false);
    }
  }

  return (
    <div className="flex h-full gap-0">
      {/* Main content */}
      <div className={`flex min-w-0 flex-1 flex-col space-y-6 transition-all ${detail ? 'pr-0' : ''}`}>
        <PageHeader
          title="Templates"
          description="Approved Meta-side message templates available for outbound campaigns."
          actions={
            isAdmin ? (
              <div className="flex items-center gap-2">
                <button
                  onClick={importFromMeta}
                  disabled={importing}
                  className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm font-medium hover:bg-muted disabled:opacity-60"
                >
                  {importing ? (
                    <Spinner />
                  ) : (
                    <Download className="h-4 w-4" />
                  )}
                  Import from Meta
                </button>
                <button
                  onClick={() => setShowCreate(true)}
                  className="flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
                >
                  <Plus className="h-4 w-4" /> New Template
                </button>
              </div>
            ) : null
          }
        />

        {importResult ? (
          <div className="flex items-center justify-between rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
            <span>
              Import complete — <strong>{importResult.imported}</strong> new,{' '}
              <strong>{importResult.updated}</strong> updated.
            </span>
            <button
              onClick={() => setImportResult(null)}
              className="text-xs underline"
            >
              Dismiss
            </button>
          </div>
        ) : null}

        <div className="flex gap-1 border-b">
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => {
                setPage(1);
                setTab(t);
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

        <div className="overflow-x-auto rounded-lg border bg-white">
          {loading ? (
            <div className="p-4">
              <SkeletonRows rows={6} />
            </div>
          ) : error ? (
            <div className="p-4">
              <ErrorBox message={error} onRetry={fetchTemplates} />
            </div>
          ) : items.length === 0 ? (
            <p className="p-6 text-center text-sm text-muted-foreground">
              No templates found.{' '}
              {isAdmin ? (
                <button
                  onClick={importFromMeta}
                  className="underline"
                  disabled={importing}
                >
                  Import from Meta
                </button>
              ) : null}
            </p>
          ) : (
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="border-b text-xs text-muted-foreground">
                <tr>
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Category</th>
                  <th className="px-4 py-3">Language</th>
                  <th className="px-4 py-3">Created</th>
                  {isAdmin ? <th className="px-4 py-3">Actions</th> : null}
                </tr>
              </thead>
              <tbody>
                {items.map((t) => (
                  <tr
                    key={t.id}
                    onClick={() => setDetail(t)}
                    className={`cursor-pointer border-b transition-colors hover:bg-muted/50 ${
                      detail?.id === t.id ? 'bg-muted/50' : ''
                    }`}
                  >
                    <td className="px-4 py-3 font-medium">{t.name}</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={t.status} />
                    </td>
                    <td className="px-4 py-3 capitalize">{t.category}</td>
                    <td className="px-4 py-3 uppercase">{t.language}</td>
                    <td className="px-4 py-3">{fmt(t.created_at)}</td>
                    {isAdmin ? (
                      <td
                        className="px-4 py-3"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <button
                          disabled={busyId === t.id}
                          onClick={() => sync(t.id)}
                          className="flex items-center gap-1 rounded-md border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
                        >
                          {busyId === t.id ? (
                            <Spinner className="h-3 w-3" />
                          ) : (
                            <RefreshCw className="h-3 w-3" />
                          )}
                          Sync
                        </button>
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {!loading && !error && items.length > 0 ? (
          <Pagination
            page={page}
            pageSize={PAGE_SIZE}
            total={total}
            onPage={setPage}
          />
        ) : null}
      </div>

      {/* Detail sidebar */}
      {detail ? (
        <div className="ml-6 flex w-96 flex-shrink-0 flex-col rounded-lg border bg-white shadow-sm">
          <div className="flex items-center justify-between border-b px-5 py-4">
            <h2 className="text-sm font-semibold">Template Details</h2>
            <button
              onClick={() => setDetail(null)}
              className="rounded-md p-1 text-muted-foreground hover:bg-muted"
              aria-label="Close"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto px-5 py-4">
            <DetailRow label="UUID" value={<span className="font-mono text-xs">{detail.id}</span>} />
            <DetailRow label="Name" value={detail.name} />
            <DetailRow label="Status" value={<StatusBadge status={detail.status} />} />
            <DetailRow label="Category" value={<span className="capitalize">{detail.category}</span>} />
            <DetailRow label="Language" value={<span className="uppercase">{detail.language}</span>} />
            <DetailRow
              label="Meta ID"
              value={
                detail.meta_template_id ? (
                  <span className="font-mono text-xs">{detail.meta_template_id}</span>
                ) : (
                  '—'
                )
              }
            />
            <DetailRow label="Created" value={fmt(detail.created_at)} />
            <DetailRow label="Updated" value={fmt(detail.updated_at)} />
            <div className="mt-3 space-y-1">
              <p className="text-xs font-medium text-muted-foreground">Body</p>
              {detail.body ? (
                <pre className="whitespace-pre-wrap rounded-md border bg-muted/50 px-3 py-2 text-xs leading-relaxed">
                  {detail.body}
                </pre>
              ) : (
                <p className="text-xs text-muted-foreground">
                  No body stored.{' '}
                  {isAdmin && detail.meta_template_id ? (
                    <button
                      onClick={() => sync(detail.id)}
                      disabled={busyId === detail.id}
                      className="underline disabled:opacity-50"
                    >
                      Sync from Meta to fetch it.
                    </button>
                  ) : null}
                </p>
              )}
            </div>
          </div>
          {isAdmin ? (
            <div className="border-t px-5 py-4">
              <button
                disabled={busyId === detail.id}
                onClick={() => sync(detail.id)}
                className="flex w-full items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm hover:bg-muted disabled:opacity-50"
              >
                {busyId === detail.id ? <Spinner /> : <RefreshCw className="h-4 w-4" />}
                Sync status from Meta
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {/* Create modal */}
      <Modal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        title="New Template"
      >
        <form onSubmit={submitCreate} className="space-y-4 text-sm">
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">
              Name
            </label>
            <input
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="order_confirmation"
              className="w-full rounded-md border px-3 py-2"
            />
            <p className="text-xs text-muted-foreground">
              Normalized to lowercase snake_case by Meta.
            </p>
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">
              Category
            </label>
            <select
              value={form.category}
              onChange={(e) =>
                setForm({
                  ...form,
                  category: e.target.value as TemplateCategory,
                })
              }
              className="w-full rounded-md border px-3 py-2 capitalize"
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c} className="capitalize">
                  {c}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">
              Language
            </label>
            <input
              required
              value={form.language}
              onChange={(e) => setForm({ ...form, language: e.target.value })}
              placeholder="en"
              className="w-full rounded-md border px-3 py-2"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">
              Body
            </label>
            <textarea
              required
              rows={5}
              value={form.body}
              onChange={(e) => setForm({ ...form, body: e.target.value })}
              placeholder="Hello {{1}}, your order {{2}} is ready."
              className="w-full rounded-md border px-3 py-2"
            />
          </div>
          <button
            type="submit"
            disabled={creating}
            className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 font-medium text-primary-foreground disabled:opacity-60"
          >
            {creating ? <Spinner className="text-primary-foreground" /> : null}
            Submit to Meta
          </button>
        </form>
      </Modal>
    </div>
  );
}
