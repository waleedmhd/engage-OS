'use client';

import { useCallback, useEffect, useState } from 'react';
import { Plus, RotateCcw, ChevronDown, ChevronRight } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import { ErrorBox, Modal, SkeletonRows, Spinner } from '@/components/shared/ui';
import { createJournal, listAccounts, listJournals, reverseJournal } from '@/lib/erp';
import type { AccountResponse, JournalEntryResponse, JournalLineRequest } from '@/types/api';

const VOUCHER_TYPES = [
  { value: 'journal_entry', label: 'Journal Entry' },
  { value: 'bank_entry', label: 'Bank Entry' },
  { value: 'cash_entry', label: 'Cash Entry' },
  { value: 'contra_entry', label: 'Contra Entry' },
  { value: 'credit_note', label: 'Credit Note' },
  { value: 'debit_note', label: 'Debit Note' },
  { value: 'write_off', label: 'Write-Off' },
  { value: 'opening_entry', label: 'Opening Entry' },
  { value: 'exchange_gain_loss', label: 'Exchange Gain/Loss' },
];

const STATUS_COLORS: Record<string, string> = {
  draft: 'bg-gray-100 text-gray-700',
  posted: 'bg-green-100 text-green-700',
  reversed: 'bg-yellow-100 text-yellow-700',
};

function fmtDate(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
}

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

const EMPTY_LINE: JournalLineRequest = {
  account_id: '',
  description: '',
  dr: 0,
  cr: 0,
  dr_base: 0,
  cr_base: 0,
};

export default function JournalsPage() {
  const [entries, setEntries] = useState<JournalEntryResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const [creating, setCreating] = useState(false);
  const [accounts, setAccounts] = useState<AccountResponse[]>([]);
  const [form, setForm] = useState({
    posting_date: todayISO(),
    description: '',
    voucher_type: 'journal_entry',
    lines: [{ ...EMPTY_LINE }] as JournalLineRequest[],
  });
  const [createSaving, setCreateSaving] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const [reversingId, setReversingId] = useState<string | null>(null);

  const fetchEntries = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listJournals({ limit: 100 });
      setEntries(data);
    } catch (e: any) {
      setError(e?.message || 'Failed to load journals.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchEntries();
  }, [fetchEntries]);

  async function openCreate() {
    setCreateError(null);
    setCreating(true);
    setForm({
      posting_date: todayISO(),
      description: '',
      voucher_type: 'journal_entry',
      lines: [{ ...EMPTY_LINE }],
    });
    try {
      const acts = await listAccounts();
      setAccounts(acts);
    } catch {
      setAccounts([]);
    }
  }

  function addLine() {
    setForm((prev) => ({ ...prev, lines: [...prev.lines, { ...EMPTY_LINE }] }));
  }

  function removeLine(idx: number) {
    setForm((prev) => ({
      ...prev,
      lines: prev.lines.filter((_, i) => i !== idx),
    }));
  }

  function updateLine(idx: number, patch: Partial<JournalLineRequest>) {
    setForm((prev) => {
      const next = [...prev.lines];
      next[idx] = { ...next[idx], ...patch };
      // Keep dr_base/cr_base in sync with dr/cr for simplicity
      if ('dr' in patch) {
        next[idx].dr_base = patch.dr ?? next[idx].dr;
      }
      if ('cr' in patch) {
        next[idx].cr_base = patch.cr ?? next[idx].cr;
      }
      return { ...prev, lines: next };
    });
  }

  async function submitCreate(e: React.FormEvent) {
    e.preventDefault();
    const validLines = form.lines.filter((l) => l.account_id && (l.dr > 0 || l.cr > 0));
    if (!form.posting_date || validLines.length === 0) return;
    setCreateSaving(true);
    setCreateError(null);
    try {
      await createJournal({
        posting_date: form.posting_date,
        description: form.description.trim() || null,
        voucher_type: form.voucher_type,
        lines: validLines,
      });
      setCreating(false);
      await fetchEntries();
    } catch (e: any) {
      setCreateError(e?.message || 'Failed to create journal entry.');
    } finally {
      setCreateSaving(false);
    }
  }

  async function handleReverse(id: string) {
    setReversingId(id);
    try {
      await reverseJournal(id);
      await fetchEntries();
    } catch (e: any) {
      setError(e?.message || 'Failed to reverse entry.');
    } finally {
      setReversingId(null);
    }
  }

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // Compute line totals for display (dr/cr from first line's dr_base)
  const totalDr = (e: JournalEntryResponse) =>
    e.lines.reduce((sum, l) => sum + (l.dr_base || l.dr || 0), 0);

  const totalCr = (e: JournalEntryResponse) =>
    e.lines.reduce((sum, l) => sum + (l.cr_base || l.cr || 0), 0);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Journal Entries"
        description="Manual journal entries and system postings"
        actions={
          <button
            onClick={openCreate}
            className="flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
          >
            <Plus className="h-4 w-4" />
            New Journal Entry
          </button>
        }
      />

      <div className="overflow-x-auto rounded-lg border bg-white">
        {loading ? (
          <div className="p-4">
            <SkeletonRows rows={8} />
          </div>
        ) : error ? (
          <div className="p-4">
            <ErrorBox message={error} onRetry={fetchEntries} />
          </div>
        ) : entries.length === 0 ? (
          <p className="p-6 text-center text-sm text-muted-foreground">
            No journal entries found.
          </p>
        ) : (
          <table className="w-full min-w-[800px] text-left text-sm">
            <thead className="border-b text-xs font-medium text-muted-foreground">
              <tr>
                <th className="w-8 px-2 py-3" />
                <th className="px-4 py-3">Entry No</th>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Description</th>
                <th className="px-4 py-3">Voucher Type</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3 text-right">Debit</th>
                <th className="px-4 py-3 text-right">Credit</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <>
                  <tr
                    key={e.id}
                    className="cursor-pointer border-b hover:bg-muted"
                    onClick={() => toggleExpand(e.id)}
                  >
                    <td className="px-2 py-3">
                      {expanded.has(e.id) ? (
                        <ChevronDown className="h-4 w-4 text-muted-foreground" />
                      ) : (
                        <ChevronRight className="h-4 w-4 text-muted-foreground" />
                      )}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">{e.entry_no}</td>
                    <td className="px-4 py-3">{fmtDate(e.posting_date)}</td>
                    <td className="px-4 py-3 max-w-[200px] truncate">
                      {e.description || '—'}
                    </td>
                    <td className="px-4 py-3 text-xs capitalize">
                      {(e.voucher_type || '').replace(/_/g, ' ')}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                          STATUS_COLORS[e.status] ?? 'bg-gray-100 text-gray-700'
                        }`}
                      >
                        {e.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {totalDr(e).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {totalCr(e).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {e.status === 'posted' ? (
                        <button
                          onClick={(ev) => {
                            ev.stopPropagation();
                            handleReverse(e.id);
                          }}
                          disabled={reversingId === e.id}
                          className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium disabled:opacity-60"
                        >
                          {reversingId === e.id ? (
                            <Spinner />
                          ) : (
                            <RotateCcw className="h-3 w-3" />
                          )}
                          Reverse
                        </button>
                      ) : null}
                    </td>
                  </tr>
                  {expanded.has(e.id) ? (
                    <tr key={`${e.id}-lines`} className="bg-muted/30">
                      <td colSpan={9} className="px-8 py-3">
                        <table className="w-full text-xs">
                          <thead className="text-muted-foreground">
                            <tr>
                              <th className="py-1 text-left">Account</th>
                              <th className="py-1 text-left">Description</th>
                              <th className="py-1 text-right">Debit</th>
                              <th className="py-1 text-right">Credit</th>
                            </tr>
                          </thead>
                          <tbody>
                            {e.lines.map((l) => (
                              <tr key={l.id} className="border-t">
                                <td className="py-1.5 font-mono">{l.account_id}</td>
                                <td className="py-1.5">{l.description || '—'}</td>
                                <td className="py-1.5 text-right tabular-nums">
                                  {l.dr > 0
                                    ? l.dr.toLocaleString(undefined, { minimumFractionDigits: 2 })
                                    : '—'}
                                </td>
                                <td className="py-1.5 text-right tabular-nums">
                                  {l.cr > 0
                                    ? l.cr.toLocaleString(undefined, { minimumFractionDigits: 2 })
                                    : '—'}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  ) : null}
                </>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <Modal
        open={creating}
        onClose={() => setCreating(false)}
        title="New Journal Entry"
        maxWidth="max-w-2xl"
      >
        <form onSubmit={submitCreate} className="space-y-4 text-sm">
          {createError ? <ErrorBox message={createError} /> : null}

          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Posting Date</label>
              <input
                type="date"
                value={form.posting_date}
                onChange={(e) => setForm({ ...form, posting_date: e.target.value })}
                required
                className="w-full rounded-md border px-3 py-1.5 text-sm"
              />
            </div>
            <div className="col-span-2 space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Voucher Type</label>
              <select
                value={form.voucher_type}
                onChange={(e) => setForm({ ...form, voucher_type: e.target.value })}
                className="w-full rounded-md border px-3 py-1.5 text-sm"
              >
                {VOUCHER_TYPES.map((vt) => (
                  <option key={vt.value} value={vt.value}>
                    {vt.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Description</label>
            <input
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="e.g. Monthly accrual"
              className="w-full rounded-md border px-3 py-1.5 text-sm"
            />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-xs font-medium text-muted-foreground">Lines</label>
              <button
                type="button"
                onClick={addLine}
                className="text-xs text-primary underline"
              >
                + Add line
              </button>
            </div>
            {form.lines.map((line, idx) => (
              <div key={idx} className="grid grid-cols-12 gap-2 rounded-md border p-3">
                <div className="col-span-5 space-y-1">
                  <label className="text-[10px] font-medium text-muted-foreground">Account</label>
                  <select
                    value={line.account_id}
                    onChange={(e) => updateLine(idx, { account_id: e.target.value })}
                    className="w-full rounded-md border px-2 py-1 text-xs"
                  >
                    <option value="">Select account...</option>
                    {accounts.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.code} — {a.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="col-span-3 space-y-1">
                  <label className="text-[10px] font-medium text-muted-foreground">Description</label>
                  <input
                    value={line.description ?? ''}
                    onChange={(e) => updateLine(idx, { description: e.target.value || null })}
                    className="w-full rounded-md border px-2 py-1 text-xs"
                  />
                </div>
                <div className="col-span-2 space-y-1">
                  <label className="text-[10px] font-medium text-muted-foreground">Debit</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={line.dr || ''}
                    onChange={(e) => updateLine(idx, { dr: parseFloat(e.target.value) || 0 })}
                    className="w-full rounded-md border px-2 py-1 text-xs"
                  />
                </div>
                <div className="col-span-1 space-y-1">
                  <label className="text-[10px] font-medium text-muted-foreground">Credit</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={line.cr || ''}
                    onChange={(e) => updateLine(idx, { cr: parseFloat(e.target.value) || 0 })}
                    className="w-full rounded-md border px-2 py-1 text-xs"
                  />
                </div>
                <div className="col-span-1 flex items-end">
                  {form.lines.length > 1 ? (
                    <button
                      type="button"
                      onClick={() => removeLine(idx)}
                      className="rounded-md px-1 py-1 text-xs text-red-600 hover:bg-red-50"
                    >
                      X
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>

          <button
            type="submit"
            disabled={
              createSaving ||
              !form.posting_date ||
              form.lines.filter((l) => l.account_id && (l.dr > 0 || l.cr > 0)).length === 0
            }
            className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-60"
          >
            {createSaving ? <Spinner className="text-primary-foreground" /> : null}
            Create Journal Entry
          </button>
        </form>
      </Modal>
    </div>
  );
}
