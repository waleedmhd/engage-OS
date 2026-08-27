'use client';

import { useCallback, useEffect, useState } from 'react';
import { Plus } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import { ErrorBox, Modal, SkeletonRows, Spinner } from '@/components/shared/ui';
import { createAccount, listAccounts } from '@/lib/erp';
import type { AccountResponse } from '@/types/api';

const ACCOUNT_TYPE_COLORS: Record<string, string> = {
  asset: 'bg-blue-100 text-blue-700',
  liability: 'bg-amber-100 text-amber-700',
  equity: 'bg-green-100 text-green-700',
  revenue: 'bg-emerald-100 text-emerald-700',
  cogs: 'bg-orange-100 text-orange-700',
  opex: 'bg-red-100 text-red-700',
};

const ACCOUNT_TYPES = [
  { value: 'asset', label: 'Asset' },
  { value: 'liability', label: 'Liability' },
  { value: 'equity', label: 'Equity' },
  { value: 'revenue', label: 'Revenue' },
  { value: 'cogs', label: 'COGS' },
  { value: 'opex', label: 'Operating Expense' },
];

const NORMAL_SIDES = [
  { value: 'debit', label: 'Debit' },
  { value: 'credit', label: 'Credit' },
];

const EMPTY_FORM = { code: '', name: '', type: 'asset', description: '' };

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<AccountResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [createSaving, setCreateSaving] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const fetchAccounts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listAccounts();
      setAccounts(data);
    } catch (e: any) {
      setError(e?.message || 'Failed to load accounts.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAccounts();
  }, [fetchAccounts]);

  function openCreate() {
    setForm(EMPTY_FORM);
    setCreateError(null);
    setCreating(true);
  }

  async function submitCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!form.code.trim() || !form.name.trim()) return;
    setCreateSaving(true);
    setCreateError(null);
    try {
      const selectedType = ACCOUNT_TYPES.find((t) => t.value === form.type);
      const normalSide =
        selectedType?.value === 'asset' || selectedType?.value === 'cogs' || selectedType?.value === 'opex'
          ? 'debit'
          : 'credit';
      await createAccount({
        code: form.code.trim(),
        name: form.name.trim(),
        type: form.type,
        normal_side: normalSide,
        description: form.description.trim() || null,
      });
      setCreating(false);
      setForm(EMPTY_FORM);
      await fetchAccounts();
    } catch (e: any) {
      setCreateError(e?.message || 'Failed to create account.');
    } finally {
      setCreateSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Chart of Accounts"
        description="General ledger accounts"
        actions={
          <button
            onClick={openCreate}
            className="flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
          >
            <Plus className="h-4 w-4" />
            New Account
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
            <ErrorBox message={error} onRetry={fetchAccounts} />
          </div>
        ) : accounts.length === 0 ? (
          <p className="p-6 text-center text-sm text-muted-foreground">
            No accounts found.
          </p>
        ) : (
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="border-b text-xs font-medium text-muted-foreground">
              <tr>
                <th className="px-4 py-3">Code</th>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Normal Side</th>
                <th className="px-4 py-3">Control</th>
                <th className="px-4 py-3">Postable</th>
                <th className="px-4 py-3">Active</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((a) => (
                <tr key={a.id} className="border-b hover:bg-muted">
                  <td className="px-4 py-3 font-mono text-xs">{a.code}</td>
                  <td className="px-4 py-3">{a.name}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                        ACCOUNT_TYPE_COLORS[a.type] ?? 'bg-gray-100 text-gray-700'
                      }`}
                    >
                      {a.type}
                    </span>
                  </td>
                  <td className="px-4 py-3 capitalize">{a.normal_side}</td>
                  <td className="px-4 py-3">
                    {a.is_control ? (
                      <span className="inline-flex items-center rounded-full bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-700">
                        Control
                      </span>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {a.is_postable ? (
                      <span className="text-green-600">Yes</span>
                    ) : (
                      <span className="text-muted-foreground">No</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {a.is_active ? (
                      <span className="text-green-600">Yes</span>
                    ) : (
                      <span className="text-red-600">No</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <Modal open={creating} onClose={() => setCreating(false)} title="New Account">
        <form onSubmit={submitCreate} className="space-y-4 text-sm">
          {createError ? <ErrorBox message={createError} /> : null}
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Code</label>
            <input
              value={form.code}
              onChange={(e) => setForm({ ...form, code: e.target.value })}
              required
              placeholder="e.g. 1001"
              className="w-full rounded-md border px-3 py-1.5 text-sm"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Name</label>
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
              placeholder="e.g. Cash on Hand"
              className="w-full rounded-md border px-3 py-1.5 text-sm"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Type</label>
            <select
              value={form.type}
              onChange={(e) => setForm({ ...form, type: e.target.value })}
              className="w-full rounded-md border px-3 py-1.5 text-sm"
            >
              {ACCOUNT_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Description</label>
            <input
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="Optional"
              className="w-full rounded-md border px-3 py-1.5 text-sm"
            />
          </div>
          <button
            type="submit"
            disabled={createSaving || !form.code.trim() || !form.name.trim()}
            className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-60"
          >
            {createSaving ? <Spinner className="text-primary-foreground" /> : null}
            Create Account
          </button>
        </form>
      </Modal>
    </div>
  );
}
