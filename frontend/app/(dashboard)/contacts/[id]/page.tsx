'use client';

import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import {
  ContactStatusBadge,
  ErrorBox,
  SkeletonRows,
  Spinner,
} from '@/components/shared/ui';
import { authedFetch } from '@/lib/authedFetch';
import { fetchArray } from '@/lib/lists';
import { useAuth } from '@/hooks/useAuth';
import { AgentPicker, AI_AGENT_SENTINEL } from '@/components/contacts/AgentPicker';
import { ErpSummary } from '@/components/contacts/ErpSummary';
import { MarketIntelligence } from '@/components/contacts/MarketIntelligence';
import { listUsers } from '@/lib/contacts';
import type {
  ContactResponse,
  ContactStatus,
  ContactTagResponse,
  ContactUpdateRequest,
  TagWithUsage,
  UserResponse,
} from '@/types/api';

const STATUSES: ContactStatus[] = [
  'active',
  'contacted',
  'follow_up',
  'interested',
  'not_interested',
  'inactive',
  'blocked',
];

function fmt(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
}

function fmtDatetime(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleString([], {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
}

function fmtCurrency(val?: number | null): string {
  if (val == null) return '—';
  return `$${Number(val).toFixed(2)}`;
}

export default function ContactDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [contact, setContact] = useState<ContactResponse | null>(null);
  const [contactTags, setContactTags] = useState<
    { tagId: string; name: string; color: string | null }[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<ContactUpdateRequest>({});
  const [saving, setSaving] = useState(false);

  const [users, setUsers] = useState<UserResponse[] | null>(null);

  useEffect(() => {
    if (!isAdmin) return;
    listUsers()
      .then(setUsers)
      .catch(() => setUsers([]));
  }, [isAdmin]);

  const fetchContact = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const [c, rawContactTags, allTags] = await Promise.all([
        authedFetch<ContactResponse>(`/contacts/${id}`),
        fetchArray<ContactTagResponse>(`/categorization/contacts/${id}/tags`).catch(
          () => [] as ContactTagResponse[],
        ),
        fetchArray<TagWithUsage>('/categorization/tags?limit=500&offset=0').catch(
          () => [] as TagWithUsage[],
        ),
      ]);
      setContact(c);

      const tagMap = new Map<string, TagWithUsage>(
        allTags.map((t) => [t.id, t]),
      );
      setContactTags(
        (rawContactTags as ContactTagResponse[]).map((ct) => {
          const t = tagMap.get(ct.tag_id);
          return {
            tagId: ct.tag_id,
            name: t?.name ?? ct.tag_id.slice(0, 8),
            color: t?.color ?? null,
          };
        }),
      );
    } catch {
      setError('Failed to load contact.');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchContact();
  }, [fetchContact]);

  function startEditing() {
    if (!contact) return;
    setForm({
      name: contact.name ?? '',
      company: contact.company ?? '',
      notes: contact.notes ?? '',
      information: contact.information ?? '',
      status: contact.status,
      assigned_agent_id: contact.ai_assigned
        ? AI_AGENT_SENTINEL
        : (contact.assigned_agent_id ?? ''),
      ai_assigned: contact.ai_assigned,
    });
    setEditing(true);
  }

  function cancelEditing() {
    setEditing(false);
    setError(null);
  }

  async function saveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!contact) return;
    setSaving(true);
    setError(null);
    try {
      const isAI = form.ai_assigned;
      const updated = await authedFetch<ContactResponse>(
        `/contacts/${contact.id}`,
        {
          method: 'PATCH',
          json: {
            ...form,
            assigned_agent_id: isAI ? null : (form.assigned_agent_id || null),
            ai_assigned: isAI ? true : (form.ai_assigned ?? false),
          },
        },
      );
      setContact(updated);
      setEditing(false);
    } catch {
      setError('Failed to save contact.');
    } finally {
      setSaving(false);
    }
  }

  async function markStatus(newStatus: ContactStatus) {
    if (!contact) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await authedFetch<ContactResponse>(
        `/contacts/${contact.id}`,
        {
          method: 'PATCH',
          json: { status: newStatus },
        },
      );
      setContact(updated);
    } catch {
      setError('Failed to update status.');
    } finally {
      setSaving(false);
    }
  }

  // -------- loading skeleton --------
  if (loading) {
    return (
      <div className="space-y-6">
        <PageHeader title="Contact" />
        <SkeletonRows rows={8} />
      </div>
    );
  }

  // -------- error or not found --------
  if (error && !contact) {
    return (
      <div className="space-y-6">
        <PageHeader title="Contact" />
        <ErrorBox message={error} onRetry={fetchContact} />
      </div>
    );
  }

  if (!contact) {
    return (
      <div className="space-y-6">
        <PageHeader title="Contact" />
        <ErrorBox message="Contact not found." />
      </div>
    );
  }

  // -------- content --------
  return (
    <div className="space-y-6">
      <PageHeader
        title={contact.name || contact.phone}
        description="Contact details and activity"
        actions={
          <Link
            href="/contacts"
            className="flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm text-muted-foreground hover:bg-muted"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Contacts
          </Link>
        }
      />

      {error ? (
        <ErrorBox message={error} onRetry={() => setError(null)} />
      ) : null}

      <div className="grid gap-6 lg:grid-cols-3">
        {/* ========== main column: details ========== */}
        <div className="space-y-6 lg:col-span-2">
          {editing ? (
            <form
              onSubmit={saveEdit}
              className="rounded-lg border bg-white p-6"
            >
              <h2 className="text-sm font-semibold">Edit Contact</h2>

              <div className="mt-4 space-y-4">
                <Field label="Name">
                  <input
                    value={form.name ?? ''}
                    onChange={(e) =>
                      setForm({ ...form, name: e.target.value })
                    }
                    className="w-full rounded-md border px-3 py-2 text-sm"
                  />
                </Field>
                <Field label="Company">
                  <input
                    value={form.company ?? ''}
                    onChange={(e) =>
                      setForm({ ...form, company: e.target.value })
                    }
                    className="w-full rounded-md border px-3 py-2 text-sm"
                  />
                </Field>
                <Field label="Notes">
                  <textarea
                    value={form.notes ?? ''}
                    onChange={(e) =>
                      setForm({ ...form, notes: e.target.value })
                    }
                    rows={3}
                    className="w-full resize-none rounded-md border px-3 py-2 text-sm"
                  />
                </Field>
                <Field label="Information">
                  <textarea
                    value={form.information ?? ''}
                    onChange={(e) =>
                      setForm({ ...form, information: e.target.value })
                    }
                    rows={4}
                    className="w-full resize-none rounded-md border px-3 py-2 text-sm"
                  />
                </Field>
                <Field label="Status">
                  <select
                    value={form.status}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        status: e.target.value as ContactStatus,
                      })
                    }
                    className="w-full rounded-md border px-3 py-2 text-sm"
                  >
                    {STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </Field>
                {isAdmin ? (
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
                          setForm({
                            ...form,
                            assigned_agent_id: e.target.value,
                          })
                        }
                        placeholder="agent UUID"
                        className="w-full rounded-md border px-3 py-2 text-sm"
                      />
                    )}
                  </Field>
                ) : null}
              </div>

              <div className="mt-5 flex gap-2">
                <button
                  type="submit"
                  disabled={saving}
                  className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-60"
                >
                  {saving ? (
                    <Spinner className="text-primary-foreground" />
                  ) : null}
                  Save
                </button>
                <button
                  type="button"
                  onClick={cancelEditing}
                  className="rounded-md border px-4 py-2 text-sm hover:bg-muted"
                >
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            /* read-only detail card */
            <div className="rounded-lg border bg-white p-6">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold">Details</h2>
                <div className="flex items-center gap-2">
                  {['contacted', 'follow_up', 'active'].includes(
                    contact.status,
                  ) ? (
                    <>
                      <button
                        onClick={() => markStatus('interested')}
                        disabled={saving}
                        className="rounded-md border border-green-300 bg-green-50 px-3 py-1.5 text-xs font-medium text-green-700 hover:bg-green-100 disabled:opacity-50"
                      >
                        ✓ Interested
                      </button>
                      <button
                        onClick={() => markStatus('not_interested')}
                        disabled={saving}
                        className="rounded-md border border-red-300 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-100 disabled:opacity-50"
                      >
                        ✗ Not Interested
                      </button>
                    </>
                  ) : null}
                  <button
                    onClick={startEditing}
                    className="rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-muted"
                  >
                    Edit
                  </button>
                </div>
              </div>

              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <Detail label="Phone" value={contact.phone} />
                <Detail label="Name" value={contact.name || '—'} />
                <Detail label="Company" value={contact.company || '—'} />
                <Detail label="Status">
                  <ContactStatusBadge status={contact.status as ContactStatus} />
                </Detail>
                <Detail
                  label="Assigned Agent"
                  value={
                    contact.ai_assigned
                      ? 'AI Agent'
                      : (contact.assigned_agent_id || '—')
                  }
                />
              </div>

              {contact.notes ? (
                <div className="mt-4 border-t pt-4">
                  <p className="text-xs text-muted-foreground">Notes</p>
                  <p className="mt-1 whitespace-pre-wrap text-sm">
                    {contact.notes}
                  </p>
                </div>
              ) : null}

              {contact.information ? (
                <div className="mt-4 border-t pt-4">
                  <p className="text-xs text-muted-foreground">Information</p>
                  <p className="mt-1 whitespace-pre-wrap text-sm">
                    {contact.information}
                  </p>
                </div>
              ) : null}
            </div>
          )}
        </div>

        {/* ========== sidebar ========== */}
        <div className="space-y-6">
          {/* Activity stats */}
          <div className="rounded-lg border bg-white p-6">
            <h2 className="text-sm font-semibold">Activity</h2>
            <div className="mt-3 space-y-2.5">
              <Stat
                label="Conversations"
                value={contact.conversation_count}
              />
              <Stat
                label="Revenue Attributed"
                value={fmtCurrency(contact.revenue_attributed)}
              />
              <Stat
                label="Estimated LTV"
                value={fmtCurrency(contact.estimated_ltv)}
              />
              <Stat
                label="Last Interaction"
                value={fmt(contact.last_interaction_at)}
              />
              <Stat
                label="Last Contacted"
                value={fmt(contact.last_contacted_at)}
              />
              <Stat
                label="Last Inbound"
                value={fmt(contact.last_inbound_at)}
              />
              <Stat
                label="Created"
                value={fmtDatetime(contact.created_at)}
              />
              <Stat
                label="Updated"
                value={fmtDatetime(contact.updated_at)}
              />
            </div>
          </div>

          {/* Tags */}
          <div className="rounded-lg border bg-white p-6">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold">Tags</h2>
              {contactTags.length > 0 ? (
                <span className="text-xs text-muted-foreground">
                  {contactTags.length}
                </span>
              ) : null}
            </div>

            <div className="mt-3">
              {contactTags.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No tags assigned.
                </p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {contactTags.map((t) => (
                    <span
                      key={t.tagId}
                      className="inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium"
                      style={{
                        borderColor: t.color ?? undefined,
                        backgroundColor: t.color
                          ? `${t.color}20`
                          : undefined,
                      }}
                    >
                      <span
                        className="inline-block h-2 w-2 rounded-full"
                        style={{
                          backgroundColor: t.color ?? '#e5e7eb',
                        }}
                      />
                      {t.name}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Market Intelligence */}
          <div className="rounded-lg border bg-white p-6">
            <h2 className="text-sm font-semibold">Market Intelligence</h2>
            <div className="mt-3">
              <MarketIntelligence contactId={contact.id} />
            </div>
          </div>

          {/* ERP Summary */}
          <div className="rounded-lg border bg-white p-6">
            <h2 className="text-sm font-semibold">ERP Summary</h2>
            <div className="mt-3">
              <ErpSummary contactId={contact.id} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------- helpers

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

function Detail({
  label,
  value,
  children,
}: {
  label: string;
  value?: string | number;
  children?: React.ReactNode;
}) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      {children ?? <p className="mt-0.5 text-sm">{value}</p>}
    </div>
  );
}

function Stat({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium tabular-nums">{value}</span>
    </div>
  );
}
