'use client';

import { useCallback, useEffect, useState } from 'react';
import clsx from 'clsx';
import { Plus } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import { EmptyState } from '@/components/shared/EmptyState';
import {
  ErrorBox,
  Modal,
  Pagination,
  SkeletonRows,
  Spinner,
} from '@/components/shared/ui';
import ContactPicker from '@/components/campaigns/ContactPicker';
import { authedFetch } from '@/lib/authedFetch';
import { fetchArray, fetchPage } from '@/lib/lists';
import type {
  CampaignCategoryWithUsage,
  CampaignComplianceError,
  CampaignCreateRequest,
  CampaignReport,
  CampaignResponse,
  CampaignType,
  CampaignValidateResult,
  TagResponse,
  TemplateResponse,
} from '@/types/api';

const PAGE_SIZE = 20;
const TABS = [
  'all',
  'draft',
  'scheduled',
  'running',
  'completed',
  'failed',
] as const;

const CONTACT_STATUSES = [
  'active',
  'inactive',
  'blocked',
  'contacted',
  'follow_up',
  'interested',
  'not_interested',
] as const;

function fmt(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
}

export default function CampaignsPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]>('all');
  const [items, setItems] = useState<CampaignResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showCreate, setShowCreate] = useState(false);
  const [tags, setTags] = useState<TagResponse[]>([]);
  const [categories, setCategories] = useState<CampaignCategoryWithUsage[]>([]);
  const [templates, setTemplates] = useState<TemplateResponse[]>([]);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState<CampaignCreateRequest>({
    name: '',
    template_id: '',
    type: 'immediate',
    audience_filter: { tags: [], status: [], contact_ids: [] },
    category_id: null,
  });

  const [createError, setCreateError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [validateResult, setValidateResult] =
    useState<CampaignValidateResult | null>(null);
  const [validatedId, setValidatedId] = useState<string | null>(null);
  const [report, setReport] = useState<CampaignReport | null>(null);
  const [detailCampaign, setDetailCampaign] = useState<CampaignResponse | null>(null);
  const [detailReport, setDetailReport] = useState<CampaignReport | null>(null);
  const [showEdit, setShowEdit] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState<{
    name: string;
    scheduled_at: string;
    audience_filter: CampaignCreateRequest['audience_filter'];
  }>({ name: '', scheduled_at: '', audience_filter: { tags: [], status: [], contact_ids: [] } });
  const [deleteTarget, setDeleteTarget] = useState<CampaignResponse | null>(null);

  const fetchCampaigns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
      });
      if (tab !== 'all') params.set('status', tab);
      const res = await fetchPage<CampaignResponse>(
        `/campaigns?${params.toString()}`,
      );
      setItems(res.items);
      setTotal(res.total);
    } catch {
      setError('Failed to load campaigns.');
    } finally {
      setLoading(false);
    }
  }, [tab, page]);

  useEffect(() => {
    fetchCampaigns();
  }, [fetchCampaigns]);

  async function openCreate() {
    setShowCreate(true);
    setCreateError(null);
    try {
      setTags(await fetchArray<TagResponse>('/categorization/tags'));
    } catch {
      setTags([]);
    }
    try {
      setCategories(
        await fetchArray<CampaignCategoryWithUsage>(
          '/campaign-categories?limit=500',
        ),
      );
    } catch {
      setCategories([]);
    }
    try {
      // Fetch only approved templates so users can only pick valid ones.
      setTemplates(
        await fetchArray<TemplateResponse>('/templates?status=approved&page_size=200'),
      );
    } catch {
      setTemplates([]);
    }
  }

  async function submitCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    setCreateError(null);
    try {
      await authedFetch<CampaignResponse>('/campaigns', {
        method: 'POST',
        json: form,
      });
      setShowCreate(false);
      setForm({
        name: '',
        template_id: '',
        type: 'immediate',
        audience_filter: { tags: [], status: [], contact_ids: [] },
        category_id: null,
      });
      await fetchCampaigns();
    } catch {
      setCreateError('Failed to create campaign. Check that the Template ID is a valid UUID and the category (if selected) exists.');
    } finally {
      setCreating(false);
    }
  }

  async function validate(id: string) {
    setBusyId(id);
    setValidatedId(id);
    try {
      const r = await authedFetch<CampaignValidateResult>(
        `/campaigns/${id}/validate`,
        { method: 'POST' },
      );
      setValidateResult(r);
    } catch {
      setError('Validation failed.');
    } finally {
      setBusyId(null);
    }
  }

  async function launch(id: string) {
    setBusyId(id);
    try {
      await authedFetch(`/campaigns/${id}/launch`, {
        method: 'POST',
        json: { confirm: true },
      });
      setValidateResult(null);
      setValidatedId(null);
      await fetchCampaigns();
    } catch {
      setError('Launch failed.');
    } finally {
      setBusyId(null);
    }
  }

  async function cancel(id: string) {
    setBusyId(id);
    try {
      await authedFetch(`/campaigns/${id}/cancel`, { method: 'POST' });
      await fetchCampaigns();
    } catch {
      setError('Cancel failed.');
    } finally {
      setBusyId(null);
    }
  }

  async function openEdit(c: CampaignResponse) {
    setEditForm({
      name: c.name,
      scheduled_at: c.scheduled_at?.slice(0, 16) ?? '',
      audience_filter: {
        tags: c.audience_filter?.tags ?? [],
        status: c.audience_filter?.status ?? [],
        contact_ids: c.audience_filter?.contact_ids ?? [],
      },
    });
    if (tags.length === 0) {
      try {
        setTags(await fetchArray<TagResponse>('/categorization/tags'));
      } catch {
        setTags([]);
      }
    }
    setShowEdit(true);
  }

  async function submitEdit(e: React.FormEvent) {
    e.preventDefault();
    setEditing(true);
    try {
      const detailTarget = detailCampaign!;
      const body: Record<string, unknown> = {};
      if (editForm.name) body.name = editForm.name;
      if (editForm.scheduled_at) body.scheduled_at = editForm.scheduled_at;
      if (editForm.audience_filter) body.audience_filter = editForm.audience_filter;
      await authedFetch(`/campaigns/${detailTarget.id}`, {
        method: 'PATCH',
        json: body,
      });
      setShowEdit(false);
      setDetailCampaign(null);
      await fetchCampaigns();
    } catch {
      setError('Edit failed.');
    } finally {
      setEditing(false);
    }
  }

  function confirmDelete(c: CampaignResponse) {
    setDeleteTarget(c);
  }

  async function executeDelete() {
    if (!deleteTarget) return;
    setBusyId(deleteTarget.id);
    try {
      await authedFetch(`/campaigns/${deleteTarget.id}/cancel`, { method: 'POST' });
      setDeleteTarget(null);
      setDetailCampaign(null);
      await fetchCampaigns();
    } catch {
      setError('Delete failed.');
    } finally {
      setBusyId(null);
    }
  }

  async function viewReport(id: string) {
    setBusyId(id);
    try {
      setReport(await authedFetch<CampaignReport>(`/campaigns/${id}/report`));
    } catch {
      setError('Failed to load report.');
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Campaigns"
        description="Template-based broadcasts: immediate, scheduled, or recurring."
        actions={
          <button
            onClick={openCreate}
            className="flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
          >
            <Plus className="h-4 w-4" /> New Campaign
          </button>
        }
      />

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
            <ErrorBox message={error} onRetry={fetchCampaigns} />
          </div>
        ) : items.length === 0 ? (
          <p className="p-6 text-center text-sm text-muted-foreground">
            No campaigns found.
          </p>
        ) : (
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="border-b text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Audience</th>
                <th className="px-4 py-3">Sent / Delivered / Failed</th>
                <th className="px-4 py-3">Scheduled At</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr
                  key={c.id}
                  className="cursor-pointer border-b hover:bg-muted/50"
                  onClick={() => {
                    setDetailCampaign(c);
                    if (c.status === 'failed' || c.status === 'completed') {
                      setDetailReport(null);
                      authedFetch<CampaignReport>(`/campaigns/${c.id}/report`)
                        .then(setDetailReport)
                        .catch(() => setDetailReport(null));
                    } else {
                      setDetailReport(null);
                    }
                  }}
                >
                  <td className="px-4 py-3 font-medium">{c.name}</td>
                  <td className="px-4 py-3 capitalize">{c.status}</td>
                  <td className="px-4 py-3 capitalize">{c.type}</td>
                  <td className="px-4 py-3">{c.audience_count}</td>
                  <td className="px-4 py-3">
                    {c.sent_count} / {c.delivered_count} / {c.failed_count}
                  </td>
                  <td className="px-4 py-3">{fmt(c.scheduled_at)}</td>
                  <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                    <div className="flex flex-wrap gap-2">
                      {c.status === 'draft' && (
                        <>
                          <button
                            disabled={busyId === c.id}
                            onClick={() => validate(c.id)}
                            className="rounded-md border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
                          >
                            Validate
                          </button>
                          <button
                            disabled={busyId === c.id}
                            onClick={() => openEdit(c)}
                            className="rounded-md border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
                          >
                            Edit
                          </button>
                        </>
                      )}
                      {((c.status === 'scheduled' && c.type === 'immediate') ||
                        (validatedId === c.id && validateResult?.ok)) && (
                        <button
                          disabled={busyId === c.id}
                          onClick={() => launch(c.id)}
                          className="rounded-md bg-primary px-2 py-1 text-xs text-primary-foreground disabled:opacity-50"
                        >
                          Launch
                        </button>
                      )}
                      {(c.status === 'scheduled' ||
                        c.status === 'queued' ||
                        c.status === 'dispatching') && (
                        <button
                          disabled={busyId === c.id}
                          onClick={() => confirmDelete(c)}
                          className="rounded-md bg-red-600 px-2 py-1 text-xs text-white hover:bg-red-700 disabled:opacity-50"
                        >
                          Cancel
                        </button>
                      )}
                      {(c.status === 'completed' || c.status === 'failed') && (
                        <button
                          disabled={busyId === c.id}
                          onClick={() => viewReport(c.id)}
                          className="rounded-md border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
                        >
                          View Report
                        </button>
                      )}
                      {c.status !== 'completed' &&
                        c.status !== 'failed' &&
                        c.status !== 'cancelled' && (
                          <button
                            disabled={busyId === c.id}
                            onClick={() => confirmDelete(c)}
                            className="rounded-md border border-red-200 px-2 py-1 text-xs text-red-600 hover:bg-red-50 disabled:opacity-50"
                          >
                            Delete
                          </button>
                        )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {validateResult && validatedId ? (
        <div
          className={`rounded-md border p-4 text-sm ${
            validateResult.ok
              ? 'border-green-200 bg-green-50'
              : 'border-red-200 bg-red-50'
          }`}
        >
          <p className="font-medium">
            {validateResult.ok ? 'Validation passed' : 'Validation failed'} ·{' '}
            {validateResult.recipient_count} recipients
          </p>
          {validateResult.errors.length > 0 ? (
            <ul className="mt-2 list-disc pl-5 text-xs text-red-700">
              {validateResult.errors.map((er: CampaignComplianceError, i) => (
                <li key={i}>{er.message}</li>
              ))}
            </ul>
          ) : null}
          <button
            onClick={() => {
              setValidateResult(null);
              setValidatedId(null);
            }}
            className="mt-2 text-xs underline"
          >
            Dismiss
          </button>
        </div>
      ) : null}

      {!loading && !error && items.length > 0 ? (
        <Pagination
          page={page}
          pageSize={PAGE_SIZE}
          total={total}
          onPage={setPage}
        />
      ) : null}

      {/* Create modal */}
      <Modal
        open={showCreate}
        onClose={() => { setShowCreate(false); setCreateError(null); }}
        title="New Campaign"
        maxWidth="max-w-2xl"
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
              className="w-full rounded-md border px-3 py-2"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">
              Template
            </label>
            {templates.length === 0 ? (
              <p className="rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-700">
                No approved templates found. Submit and get a template approved first.
              </p>
            ) : (
              <select
                required
                value={form.template_id}
                onChange={(e) => setForm({ ...form, template_id: e.target.value })}
                className="w-full rounded-md border px-3 py-2 text-sm"
              >
                <option value="">— Select a template —</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} ({t.language})
                  </option>
                ))}
              </select>
            )}
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">
              Type
            </label>
            <div className="flex gap-4">
              {(['immediate', 'scheduled', 'recurring'] as CampaignType[]).map(
                (t) => (
                  <label key={t} className="flex items-center gap-1 capitalize">
                    <input
                      type="radio"
                      name="type"
                      checked={form.type === t}
                      onChange={() => setForm({ ...form, type: t })}
                    />
                    {t}
                  </label>
                ),
              )}
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">
              Category (optional)
            </label>
            <select
              value={form.category_id ?? ''}
              onChange={(e) =>
                setForm({
                  ...form,
                  category_id: e.target.value || null,
                })
              }
              className="w-full rounded-md border px-3 py-2"
            >
              <option value="">— None —</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          {form.type === 'scheduled' ? (
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">
                Scheduled At
              </label>
              <input
                type="datetime-local"
                value={form.scheduled_at ?? ''}
                onChange={(e) =>
                  setForm({ ...form, scheduled_at: e.target.value })
                }
                className="w-full rounded-md border px-3 py-2"
              />
            </div>
          ) : null}
          {form.type === 'recurring' ? (
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">
                Cron Expression
              </label>
              <input
                value={form.cron_expression ?? ''}
                onChange={(e) =>
                  setForm({ ...form, cron_expression: e.target.value })
                }
                placeholder="0 9 * * 1"
                className="w-full rounded-md border px-3 py-2"
              />
            </div>
          ) : null}
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">
              Audience tags
            </label>
            <div className="max-h-32 space-y-1 overflow-y-auto rounded-md border p-2">
              {tags.length === 0 ? (
                <p className="text-xs text-muted-foreground">No tags</p>
              ) : (
                tags.map((t) => {
                  const sel = form.audience_filter.tags ?? [];
                  return (
                    <label key={t.id} className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={sel.includes(t.id)}
                        onChange={(e) =>
                          setForm({
                            ...form,
                            audience_filter: {
                              ...form.audience_filter,
                              tags: e.target.checked
                                ? [...sel, t.id]
                                : sel.filter((x) => x !== t.id),
                            },
                          })
                        }
                      />
                      {t.name}
                    </label>
                  );
                })
              )}
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">
              Contact Status
            </label>
            <div className="max-h-32 space-y-1 overflow-y-auto rounded-md border p-2">
              {CONTACT_STATUSES.map((s) => {
                const sel = form.audience_filter.status ?? [];
                return (
                  <label key={s} className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={sel.includes(s)}
                      onChange={(e) =>
                        setForm({
                          ...form,
                          audience_filter: {
                            ...form.audience_filter,
                            status: e.target.checked
                              ? [...sel, s]
                              : sel.filter((x) => x !== s),
                          },
                        })
                      }
                    />
                    <span className="capitalize">{s.replace(/_/g, ' ')}</span>
                  </label>
                );
              })}
            </div>
            <p className="text-xs text-muted-foreground">
              Leave all unchecked to include all statuses. Blocked contacts are
              always excluded.
            </p>
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">
              Specific Contacts (optional)
            </label>
            <ContactPicker
              selectedIds={
                new Set(form.audience_filter.contact_ids ?? [])
              }
              onSelectionChange={(newSet) =>
                setForm({
                  ...form,
                  audience_filter: {
                    ...form.audience_filter,
                    contact_ids: Array.from(newSet),
                  },
                })
              }
            />
            <p className="text-xs text-muted-foreground">
              When specific contacts are selected, they are combined with any
              tag/type filters above (AND logic).
            </p>
          </div>
          {createError ? (
            <p className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-700">
              {createError}
            </p>
          ) : null}
          <button
            type="submit"
            disabled={creating}
            className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 font-medium text-primary-foreground disabled:opacity-60"
          >
            {creating ? <Spinner className="text-primary-foreground" /> : null}
            Create
          </button>
        </form>
      </Modal>

      {/* Report modal */}
      <Modal
        open={Boolean(report)}
        onClose={() => setReport(null)}
        title="Campaign Report"
      >
        {report ? (
          <div className="space-y-2 text-sm">
            <Row k="Status" v={report.status} />
            <Row k="Audience" v={report.audience_count} />
            <Row k="Sent" v={report.sent_count} />
            <Row k="Delivered" v={report.delivered_count} />
            <Row k="Failed" v={report.failed_count} />
            <Row k="Responses" v={report.response_count} />
            <Row k="Pending" v={report.pending_count} />
            <Row
              k="Delivery rate"
              v={`${(report.delivery_rate * 100).toFixed(1)}%`}
            />
            <Row
              k="Failure rate"
              v={`${(report.failure_rate * 100).toFixed(1)}%`}
            />
            <Row
              k="Response rate"
              v={`${(report.response_rate * 100).toFixed(1)}%`}
            />
            <Row k="Started" v={fmt(report.started_at)} />
            <Row k="Completed" v={fmt(report.completed_at)} />
            {report.duration_seconds != null ? (
              <Row k="Duration (s)" v={report.duration_seconds} />
            ) : null}
            {report.error_breakdown.length > 0 ? (
              <div className="mt-4 border-t pt-3">
                <p className="mb-2 text-xs font-medium text-red-600">
                  Failure Reasons
                </p>
                <div className="space-y-1.5">
                  {report.error_breakdown.map((er, i) => {
                    const maxCount = report.error_breakdown[0].count;
                    const pct = (er.count / maxCount) * 100;
                    return (
                      <div key={i} className="flex items-center gap-2 text-xs">
                        <span className="w-10 text-right tabular-nums text-muted-foreground">
                          {er.count}
                        </span>
                        <div className="flex-1 rounded bg-red-100">
                          <div
                            className="rounded bg-red-400 h-5"
                            style={{ width: `${Math.max(pct, 4)}%` }}
                          />
                        </div>
                        <span className="flex-1 truncate" title={er.error_message}>
                          {er.error_message}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : report.status === 'failed' ? (
              <div className="mt-4 border-t pt-3">
                <p className="text-xs text-red-600">
                  Campaign failed, but no recipient-level error details are available.
                  Check the worker logs or the campaign&apos;s validation errors.
                </p>
              </div>
            ) : report.failed_count > 0 ? (
              <div className="mt-4 border-t pt-3">
                <p className="text-xs text-amber-600">
                  {report.failed_count} recipient(s) failed, but no error details recorded.
                </p>
              </div>
            ) : null}
          </div>
        ) : null}
      </Modal>

      {/* Detail modal */}
      <Modal
        open={Boolean(detailCampaign)}
        onClose={() => { setDetailCampaign(null); setDetailReport(null); }}
        title="Campaign Details"
        maxWidth="max-w-lg"
      >
        {detailCampaign ? (
          <div className="space-y-4 text-sm">
            <div className="flex items-center gap-2">
              <span className={clsx(
                'rounded-full px-2.5 py-0.5 text-xs font-medium capitalize',
                detailCampaign.status === 'draft' && 'bg-gray-100 text-gray-700',
                detailCampaign.status === 'scheduled' && 'bg-blue-100 text-blue-700',
                detailCampaign.status === 'validating' && 'bg-yellow-100 text-yellow-700',
                (detailCampaign.status === 'queued' || detailCampaign.status === 'dispatching') && 'bg-purple-100 text-purple-700',
                detailCampaign.status === 'completed' && 'bg-emerald-100 text-emerald-700',
                detailCampaign.status === 'failed' && 'bg-red-100 text-red-700',
                detailCampaign.status === 'cancelled' && 'bg-orange-100 text-orange-700',
              )}>
                {detailCampaign.status}
              </span>
              <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium capitalize text-muted-foreground">
                {detailCampaign.type}
              </span>
            </div>

            <div className="space-y-1.5 border-t pt-3">
              <Row k="Template" v={String(detailCampaign.template_id)} />
              <Row k="Category" v={detailCampaign.category_id ?? '—'} />
              {(detailCampaign.scheduled_at || detailCampaign.cron_expression) ? (
                <Row k="Scheduled" v={detailCampaign.cron_expression ?? fmt(detailCampaign.scheduled_at)} />
              ) : null}
              <Row k="Rate limit" v={detailCampaign.rate_limit_per_second ? `${detailCampaign.rate_limit_per_second}/s` : 'default'} />
            </div>

            <div className="space-y-1.5 border-t pt-3">
              <p className="text-xs font-medium text-muted-foreground">Audience</p>
              {detailCampaign.audience_filter.tags?.length ? (
                <p className="text-xs">Tags: {detailCampaign.audience_filter.tags.length} selected</p>
              ) : null}
              {detailCampaign.audience_filter.contact_ids?.length ? (
                <p className="text-xs">Specific contacts: {detailCampaign.audience_filter.contact_ids.length} selected</p>
              ) : null}
              <Row k="Total recipients" v={detailCampaign.audience_count} />
            </div>

            <div className="space-y-1.5 border-t pt-3">
              <p className="text-xs font-medium text-muted-foreground">Counters</p>
              <div className="grid grid-cols-4 gap-2">
                {[
                  ['Sent', detailCampaign.sent_count],
                  ['Delivered', detailCampaign.delivered_count],
                  ['Failed', detailCampaign.failed_count],
                  ['Responses', detailCampaign.response_count],
                ].map(([label, val]) => (
                  <div key={label} className="rounded-md border bg-muted/30 p-2 text-center">
                    <div className="text-lg font-semibold">{val}</div>
                    <div className="text-[10px] text-muted-foreground">{label}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="space-y-1.5 border-t pt-3">
              <p className="text-xs font-medium text-muted-foreground">Timeline</p>
              <Row k="Created" v={fmt(detailCampaign.created_at)} />
              <Row k="Started" v={fmt(detailCampaign.started_at)} />
              <Row k="Completed" v={fmt(detailCampaign.completed_at)} />
            </div>

            {detailCampaign.validation_errors?.length > 0 && (
              <div className="space-y-1.5 border-t pt-3">
                <p className="text-xs font-medium text-red-600">Validation Errors</p>
                <ul className="list-disc pl-5 text-xs text-red-700">
                  {(detailCampaign.validation_errors as unknown[]).map((er: unknown, i: number) => (
                    <li key={i}>{typeof er === 'string' ? er : (er as Record<string, string>).message ?? JSON.stringify(er)}</li>
                  ))}
                </ul>
              </div>
            )}

            {detailReport?.error_breakdown.length ? (
              <div className="space-y-1.5 border-t pt-3">
                <p className="mb-2 text-xs font-medium text-red-600">Failure Reasons</p>
                <div className="space-y-1.5">
                  {detailReport.error_breakdown.map((er, i) => {
                    const maxCount = detailReport.error_breakdown[0].count;
                    const pct = (er.count / maxCount) * 100;
                    return (
                      <div key={i} className="flex items-center gap-2 text-xs">
                        <span className="w-10 text-right tabular-nums text-muted-foreground">
                          {er.count}
                        </span>
                        <div className="flex-1 rounded bg-red-100">
                          <div
                            className="rounded bg-red-400 h-4"
                            style={{ width: `${Math.max(pct, 4)}%` }}
                          />
                        </div>
                        <span className="w-32 truncate" title={er.error_message}>
                          {er.error_message}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : detailCampaign.status === 'failed' ? (
              <div className="space-y-1.5 border-t pt-3">
                <p className="text-xs text-red-600">
                  Campaign failed. Check worker logs or open the full report for details.
                </p>
              </div>
            ) : null}
          </div>
        ) : null}
      </Modal>

      {/* Edit modal */}
      <Modal
        open={showEdit}
        onClose={() => { setShowEdit(false); }}
        title="Edit Campaign"
        maxWidth="max-w-2xl"
      >
        {detailCampaign ? (
          <form onSubmit={submitEdit} className="space-y-4 text-sm">
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">
                Name
              </label>
              <input
                value={editForm.name}
                onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                className="w-full rounded-md border px-3 py-2"
              />
            </div>
            {detailCampaign.type === 'scheduled' ? (
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">
                  Scheduled At
                </label>
                <input
                  type="datetime-local"
                  value={editForm.scheduled_at}
                  onChange={(e) =>
                    setEditForm({ ...editForm, scheduled_at: e.target.value })
                  }
                  className="w-full rounded-md border px-3 py-2"
                />
              </div>
            ) : null}
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">
                Audience tags
              </label>
              <div className="max-h-32 space-y-1 overflow-y-auto rounded-md border p-2">
                {tags.length === 0 ? (
                  <p className="text-xs text-muted-foreground">No tags</p>
                ) : (
                  tags.map((t) => {
                    const sel = editForm.audience_filter.tags ?? [];
                    return (
                      <label key={t.id} className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={sel.includes(t.id)}
                          onChange={(ev) =>
                            setEditForm({
                              ...editForm,
                              audience_filter: {
                                ...editForm.audience_filter,
                                tags: ev.target.checked
                                  ? [...sel, t.id]
                                  : sel.filter((x) => x !== t.id),
                              },
                            })
                          }
                        />
                        {t.name}
                      </label>
                    );
                  })
                )}
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">
                Contact Status
              </label>
              <div className="max-h-32 space-y-1 overflow-y-auto rounded-md border p-2">
                {CONTACT_STATUSES.map((s) => {
                  const sel = editForm.audience_filter.status ?? [];
                  return (
                    <label key={s} className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={sel.includes(s)}
                        onChange={(e) =>
                          setEditForm({
                            ...editForm,
                            audience_filter: {
                              ...editForm.audience_filter,
                              status: e.target.checked
                                ? [...sel, s]
                                : sel.filter((x) => x !== s),
                            },
                          })
                        }
                      />
                      <span className="capitalize">{s.replace(/_/g, ' ')}</span>
                    </label>
                  );
                })}
              </div>
              <p className="text-xs text-muted-foreground">
                Leave all unchecked to include all statuses. Blocked contacts are
                always excluded.
              </p>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">
                Specific Contacts (optional)
              </label>
              <ContactPicker
                selectedIds={
                  new Set(editForm.audience_filter.contact_ids ?? [])
                }
                onSelectionChange={(newSet) =>
                  setEditForm({
                    ...editForm,
                    audience_filter: {
                      ...editForm.audience_filter,
                      contact_ids: Array.from(newSet),
                    },
                  })
                }
              />
            </div>
            <button
              type="submit"
              disabled={editing}
              className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 font-medium text-primary-foreground disabled:opacity-60"
            >
              {editing ? <Spinner className="text-primary-foreground" /> : null}
              Save Changes
            </button>
          </form>
        ) : null}
      </Modal>

      {/* Delete confirmation */}
      <Modal
        open={Boolean(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
        title="Delete Campaign"
        maxWidth="max-w-sm"
      >
        {deleteTarget ? (
          <div className="space-y-4 text-sm">
            <p>
              Cancel campaign <strong>{deleteTarget.name}</strong>?
              {deleteTarget.audience_count > 0 && (
                <> Any pending messages ({deleteTarget.audience_count - deleteTarget.sent_count} remaining) will not be sent.</>
              )}
            </p>
            <p className="text-xs text-muted-foreground">
              This action cannot be undone. The campaign record will be preserved for audit purposes.
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setDeleteTarget(null)}
                className="flex-1 rounded-md border px-3 py-2 text-xs hover:bg-muted"
              >
                Keep
              </button>
              <button
                type="button"
                onClick={executeDelete}
                disabled={busyId === deleteTarget.id}
                className="flex flex-1 items-center justify-center gap-2 rounded-md bg-red-600 px-3 py-2 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                {busyId === deleteTarget.id ? <Spinner className="text-white" /> : null}
                Cancel Campaign
              </button>
            </div>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string | number }) {
  return (
    <div className="flex justify-between border-b py-1">
      <span className="text-muted-foreground">{k}</span>
      <span className="font-medium">{v}</span>
    </div>
  );
}
