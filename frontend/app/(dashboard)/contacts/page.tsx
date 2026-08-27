'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { UserPlus, Upload } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import {
  ContactStatusBadge,
  ErrorBox,
  Modal,
  Pagination,
  SkeletonRows,
  Spinner,
} from '@/components/shared/ui';
import { authedFetch } from '@/lib/authedFetch';
import { fetchPage } from '@/lib/lists';
import { useAuth } from '@/hooks/useAuth';
import { AgentPicker, AI_AGENT_SENTINEL } from '@/components/contacts/AgentPicker';
import { BulkActionBar } from '@/components/contacts/BulkActionBar';
import {
  ContactTagsEditor,
  TagChip,
} from '@/components/contacts/ContactTagsEditor';
import { createContact, listUsers } from '@/lib/contacts';
import type {
  BulkActionResponse,
  ContactCreateRequest,
  ContactImportReceipt,
  ContactResponse,
  ContactStatus,
  ContactUpdateRequest,
  UserResponse,
} from '@/types/api';

const PAGE_SIZE = 50;
const STATUSES: ContactStatus[] = [
  'active',
  'contacted',
  'follow_up',
  'interested',
  'not_interested',
  'inactive',
  'blocked',
];

const EMPTY_CREATE_FORM: ContactCreateRequest = {
  phone: '',
  name: '',
  company: '',
  status: 'active',
  information: '',
  assigned_agent_id: '',
  ai_assigned: false,
};

function fmt(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
}

export default function ContactsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [items, setItems] = useState<ContactResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');

  const [selected, setSelected] = useState<ContactResponse | null>(null);
  const [form, setForm] = useState<ContactUpdateRequest>({});
  const [saving, setSaving] = useState(false);

  const [creating, setCreating] = useState(false);
  const [createForm, setCreateForm] =
    useState<ContactCreateRequest>(EMPTY_CREATE_FORM);
  const [createSaving, setCreateSaving] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const [importBusy, setImportBusy] = useState(false);
  const [receipt, setReceipt] = useState<ContactImportReceipt | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [users, setUsers] = useState<UserResponse[] | null>(null);
  const [bulkReceipt, setBulkReceipt] = useState<
    { action: string; receipt: BulkActionResponse } | null
  >(null);

  useEffect(() => {
    if (!isAdmin) return;
    listUsers()
      .then(setUsers)
      .catch(() => setUsers([]));
  }, [isAdmin]);

  const fetchContacts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
      });
      if (q) params.set('q', q);
      if (status) params.set('status', status);
      const res = await fetchPage<ContactResponse>(
        `/contacts?${params.toString()}`,
      );
      setItems(res.items);
      setTotal(res.total);
    } catch {
      setError('Failed to load contacts.');
    } finally {
      setLoading(false);
    }
  }, [page, q, status]);

  useEffect(() => {
    fetchContacts();
  }, [fetchContacts]);

  function openContact(c: ContactResponse) {
    setSelected(c);
    setForm({
      name: c.name ?? '',
      company: c.company ?? '',
      notes: c.notes ?? '',
      information: c.information ?? '',
      status: c.status,
      assigned_agent_id: c.ai_assigned
        ? AI_AGENT_SENTINEL
        : (c.assigned_agent_id ?? ''),
      ai_assigned: c.ai_assigned,
    });
  }

  async function saveContact(e: React.FormEvent) {
    e.preventDefault();
    if (!selected) return;
    setSaving(true);
    try {
      const isAI = form.ai_assigned;
      await authedFetch<ContactResponse>(`/contacts/${selected.id}`, {
        method: 'PATCH',
        json: {
          ...form,
          assigned_agent_id: isAI ? null : (form.assigned_agent_id || null),
          ai_assigned: isAI ? true : (form.ai_assigned ?? false),
        },
      });
      setSelected(null);
      await fetchContacts();
    } catch {
      setError('Failed to save contact.');
    } finally {
      setSaving(false);
    }
  }

  function openCreate() {
    setCreateForm(EMPTY_CREATE_FORM);
    setCreateError(null);
    setCreating(true);
  }

  async function submitCreate(e: React.FormEvent) {
    e.preventDefault();
    const phone = createForm.phone.trim();
    if (!phone) return;
    setCreateSaving(true);
    setCreateError(null);
    try {
      const isAI = createForm.ai_assigned;
      const payload: ContactCreateRequest = {
        phone,
        name: createForm.name?.trim() || undefined,
        company: createForm.company?.trim() || undefined,
        status: createForm.status,
        assigned_agent_id: isAI
          ? undefined
          : (createForm.assigned_agent_id || undefined),
        ai_assigned: isAI || createForm.ai_assigned,
      };
      await createContact(payload);
      setCreating(false);
      setCreateForm(EMPTY_CREATE_FORM);
      setPage(1);
      await fetchContacts();
    } catch (err) {
      const status = (err as { status?: number }).status;
      setCreateError(
        status === 409
          ? 'A contact with this phone already exists.'
          : 'Failed to create contact.',
      );
    } finally {
      setCreateSaving(false);
    }
  }

  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setImportBusy(true);
    setReceipt(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const r = await authedFetch<ContactImportReceipt>('/contacts/import', {
        method: 'POST',
        body: fd,
      });
      setReceipt(r);
      await fetchContacts();
    } catch {
      setError('CSV import failed.');
    } finally {
      setImportBusy(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Contacts"
        description="Buyer/seller classification, tags, revenue attribution, and assigned agents."
        actions={
          <>
            <button
              onClick={openCreate}
              className="flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
            >
              <UserPlus className="h-4 w-4" />
              New Contact
            </button>
            {isAdmin ? (
              <>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".csv"
                  onChange={handleImport}
                  className="hidden"
                />
                <button
                  onClick={() => fileRef.current?.click()}
                  disabled={importBusy}
                  className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm font-medium disabled:opacity-60"
                >
                  {importBusy ? (
                    <Spinner />
                  ) : (
                    <Upload className="h-4 w-4" />
                  )}
                  Import CSV
                </button>
              </>
            ) : null}
          </>
        }
      />

      {receipt ? (
        <div className="rounded-md border bg-white p-4 text-sm">
          <p className="font-medium">
            {receipt.created} created · {receipt.updated} updated ·{' '}
            {receipt.skipped} skipped ({receipt.total_rows} rows)
          </p>
          {receipt.errors.length > 0 ? (
            <table className="mt-3 w-full text-left text-xs">
              <thead className="text-muted-foreground">
                <tr>
                  <th className="py-1">Row</th>
                  <th className="py-1">Phone</th>
                  <th className="py-1">Error</th>
                </tr>
              </thead>
              <tbody>
                {receipt.errors.map((er, i) => (
                  <tr key={i} className="border-t">
                    <td className="py-1">{er.row}</td>
                    <td className="py-1">{er.phone ?? '—'}</td>
                    <td className="py-1 text-red-600">{er.error}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          <button
            onClick={() => setReceipt(null)}
            className="mt-3 text-xs text-muted-foreground underline"
          >
            Dismiss
          </button>
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2">
        <input
          value={q}
          onChange={(e) => {
            setPage(1);
            setSelectedIds(new Set());
            setQ(e.target.value);
          }}
          placeholder="Search…"
          className="rounded-md border px-3 py-2 text-sm outline-none focus:border-primary"
        />
        <select
          value={status}
          onChange={(e) => {
            setPage(1);
            setSelectedIds(new Set());
            setStatus(e.target.value);
          }}
          className="rounded-md border px-3 py-2 text-sm"
        >
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      <BulkActionBar
        selectedIds={Array.from(selectedIds)}
        isAdmin={isAdmin}
        users={users}
        onClear={() => setSelectedIds(new Set())}
        onDone={async (r, action) => {
          setBulkReceipt({ action, receipt: r });
          setSelectedIds(new Set());
          await fetchContacts();
        }}
      />

      {bulkReceipt ? (
        <div className="rounded-md border bg-white p-4 text-sm">
          <p className="font-medium">
            {bulkReceipt.action === 'delete'
              ? `${bulkReceipt.receipt.count} deleted`
              : `${bulkReceipt.receipt.count} updated`}
            {bulkReceipt.receipt.failed.length > 0
              ? ` · ${bulkReceipt.receipt.failed.length} failed`
              : ''}
          </p>
          {bulkReceipt.receipt.failed.length > 0 ? (
            <table className="mt-3 w-full text-left text-xs">
              <thead className="text-muted-foreground">
                <tr>
                  <th className="py-1">Contact ID</th>
                  <th className="py-1">Error</th>
                </tr>
              </thead>
              <tbody>
                {bulkReceipt.receipt.failed.map((f) => (
                  <tr key={f.id} className="border-t">
                    <td className="py-1 font-mono">{f.id}</td>
                    <td className="py-1 text-red-600">{f.error}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          <button
            onClick={() => setBulkReceipt(null)}
            className="mt-3 text-xs text-muted-foreground underline"
          >
            Dismiss
          </button>
        </div>
      ) : null}

      <div className="overflow-x-auto rounded-lg border bg-white">
        {loading ? (
          <div className="p-4">
            <SkeletonRows rows={8} />
          </div>
        ) : error ? (
          <div className="p-4">
            <ErrorBox message={error} onRetry={fetchContacts} />
          </div>
        ) : items.length === 0 ? (
          <p className="p-6 text-center text-sm text-muted-foreground">
            No contacts found.
          </p>
        ) : (
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="border-b text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-3">
                  <input
                    type="checkbox"
                    aria-label="Select all on page"
                    checked={
                      items.length > 0 &&
                      items.every((c) => selectedIds.has(c.id))
                    }
                    ref={(el) => {
                      if (el) {
                        const allSelected =
                          items.length > 0 &&
                          items.every((c) => selectedIds.has(c.id));
                        const someSelected = items.some((c) =>
                          selectedIds.has(c.id),
                        );
                        el.indeterminate = !allSelected && someSelected;
                      }
                    }}
                    onChange={(e) => {
                      setSelectedIds((prev) => {
                        const next = new Set(prev);
                        if (e.target.checked) {
                          items.forEach((c) => next.add(c.id));
                        } else {
                          items.forEach((c) => next.delete(c.id));
                        }
                        return next;
                      });
                    }}
                  />
                </th>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Phone</th>
                <th className="px-4 py-3">Company</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Tags</th>
                <th className="px-4 py-3">Assigned Agent</th>
                <th className="px-4 py-3">Last Interaction</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr
                  key={c.id}
                  onClick={() => openContact(c)}
                  className="cursor-pointer border-b hover:bg-muted"
                >
                  <td
                    className="px-3 py-3"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <input
                      type="checkbox"
                      aria-label={`Select ${c.phone}`}
                      checked={selectedIds.has(c.id)}
                      onChange={(e) => {
                        setSelectedIds((prev) => {
                          const next = new Set(prev);
                          if (e.target.checked) next.add(c.id);
                          else next.delete(c.id);
                          return next;
                        });
                      }}
                    />
                  </td>
                  <td className="px-4 py-3">{c.name || '—'}</td>
                  <td className="px-4 py-3">{c.phone}</td>
                  <td className="px-4 py-3">{c.company || '—'}</td>
                  <td className="px-4 py-3">
                  <ContactStatusBadge status={c.status as ContactStatus} />
                </td>
                  <td className="px-4 py-3">
                    {c.tags && c.tags.length > 0 ? (
                      <span className="flex flex-wrap gap-1">
                        {c.tags.map((t) => (
                          <TagChip key={t.id} tag={t} />
                        ))}
                      </span>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs">
                    {c.ai_assigned
                      ? 'AI Agent'
                      : (c.assigned_agent_id || '—')}
                  </td>
                  <td className="px-4 py-3">{fmt(c.last_interaction_at)}</td>
                  <td className="px-4 py-3 text-xs text-muted-foreground">
                    Edit
                  </td>
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
          onPage={(p) => {
            setPage(p);
            setSelectedIds(new Set());
          }}
        />
      ) : null}

      <Modal
        open={creating}
        onClose={() => setCreating(false)}
        title="New Contact"
      >
        <form onSubmit={submitCreate} className="space-y-4 text-sm">
          {createError ? <ErrorBox message={createError} /> : null}
          <Field label="Phone">
            <input
              value={createForm.phone}
              onChange={(e) =>
                setCreateForm({ ...createForm, phone: e.target.value })
              }
              required
              placeholder="+15551234567"
              className="w-full rounded-md border px-3 py-2"
            />
          </Field>
          <Field label="Name">
            <input
              value={createForm.name ?? ''}
              onChange={(e) =>
                setCreateForm({ ...createForm, name: e.target.value })
              }
              className="w-full rounded-md border px-3 py-2"
            />
          </Field>
          <Field label="Company">
            <input
              value={createForm.company ?? ''}
              onChange={(e) =>
                setCreateForm({ ...createForm, company: e.target.value })
              }
              className="w-full rounded-md border px-3 py-2"
            />
          </Field>
          <Field label="Status">
            <select
              value={createForm.status}
              onChange={(e) =>
                setCreateForm({
                  ...createForm,
                  status: e.target.value as ContactStatus,
                })
              }
              className="w-full rounded-md border px-3 py-2"
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </Field>
          {users ? (
            <Field label="Assigned Agent">
              <AgentPicker
                users={users}
                includeUnassigned
                includeAI
                value={
                  createForm.ai_assigned
                    ? AI_AGENT_SENTINEL
                    : (createForm.assigned_agent_id || null)
                }
                onChange={(v) =>
                  setCreateForm({
                    ...createForm,
                    assigned_agent_id: v === AI_AGENT_SENTINEL ? '' : (v ?? ''),
                    ai_assigned: v === AI_AGENT_SENTINEL,
                  })
                }
                className="w-full"
              />
            </Field>
          ) : null}
          <button
            type="submit"
            disabled={createSaving || !createForm.phone.trim()}
            className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 font-medium text-primary-foreground disabled:opacity-60"
          >
            {createSaving ? (
              <Spinner className="text-primary-foreground" />
            ) : null}
            Create Contact
          </button>
        </form>
      </Modal>

      <Modal
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
        title={selected?.name || selected?.phone || 'Contact'}
      >
        {selected ? (
          <form onSubmit={saveContact} className="space-y-4 text-sm">
            <div className="rounded-md bg-muted p-3 text-xs text-muted-foreground">
              {selected.phone} · {selected.conversation_count} conversations ·
              revenue {selected.revenue_attributed}
            </div>
            <Field label="Name">
              <input
                value={form.name ?? ''}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full rounded-md border px-3 py-2"
              />
            </Field>
            <Field label="Company">
              <input
                value={form.company ?? ''}
                onChange={(e) => setForm({ ...form, company: e.target.value })}
                className="w-full rounded-md border px-3 py-2"
              />
            </Field>
            <Field label="Notes">
              <textarea
                value={form.notes ?? ''}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                rows={3}
                className="w-full resize-none rounded-md border px-3 py-2"
              />
            </Field>
            <Field label="Information">
              <textarea
                value={form.information ?? ''}
                onChange={(e) => setForm({ ...form, information: e.target.value })}
                rows={4}
                className="w-full resize-none rounded-md border px-3 py-2"
              />
            </Field>
            <Field label="Status">
              <select
                value={form.status}
                onChange={(e) =>
                  setForm({ ...form, status: e.target.value as ContactStatus })
                }
                className="w-full rounded-md border px-3 py-2"
              >
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Assigned Agent">
              {users ? (
                <AgentPicker
                  users={users}
                  includeUnassigned
                  includeAI
                  value={
                    form.ai_assigned
                      ? AI_AGENT_SENTINEL
                      : (form.assigned_agent_id || null)
                  }
                  onChange={(v) =>
                    setForm({
                      ...form,
                      assigned_agent_id:
                        v === AI_AGENT_SENTINEL ? '' : (v ?? ''),
                      ai_assigned: v === AI_AGENT_SENTINEL,
                    })
                  }
                  className="w-full"
                />
              ) : (
                <input
                  value={form.assigned_agent_id ?? ''}
                  onChange={(e) =>
                    setForm({ ...form, assigned_agent_id: e.target.value })
                  }
                  placeholder="agent UUID"
                  className="w-full rounded-md border px-3 py-2"
                />
              )}
            </Field>
            <Field label="Tags">
              <ContactTagsEditor
                contactId={selected.id}
                onChange={fetchContacts}
              />
            </Field>
            <button
              type="submit"
              disabled={saving}
              className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 font-medium text-primary-foreground disabled:opacity-60"
            >
              {saving ? <Spinner className="text-primary-foreground" /> : null}
              Save
            </button>
          </form>
        ) : null}
      </Modal>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-muted-foreground">
        {label}
      </label>
      {children}
    </div>
  );
}
