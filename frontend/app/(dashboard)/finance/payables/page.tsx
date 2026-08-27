'use client';

import { useCallback, useEffect, useState } from 'react';
import { Plus, Ban, CheckCircle, Link2 } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import { ErrorBox, Modal, SkeletonRows, Spinner } from '@/components/shared/ui';
import {
  createBill,
  createSupplierPayment,
  getAPAgeing,
  issueBill,
  listBills,
  listSupplierPayments,
  voidBill,
  allocateBillPayment,
} from '@/lib/erp';
import type {
  AgeingResponse,
  BillLineRequest,
  BillResponse,
  SupplierPaymentResponse,
} from '@/types/api';

const STATUS_COLORS: Record<string, string> = {
  draft: 'bg-gray-100 text-gray-700',
  issued: 'bg-blue-100 text-blue-700',
  paid: 'bg-green-100 text-green-700',
  void: 'bg-red-100 text-red-700',
  partial: 'bg-amber-100 text-amber-700',
  unallocated: 'bg-purple-100 text-purple-700',
  allocated: 'bg-green-100 text-green-700',
};

const PAYMENT_METHODS = ['cash', 'bank_transfer', 'cheque', 'card', 'mobile_money'];

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

function dueDateISO(daysFromNow = 30): string {
  const d = new Date();
  d.setDate(d.getDate() + daysFromNow);
  return d.toISOString().slice(0, 10);
}

type Tab = 'bills' | 'payments' | 'ageing';

const TABS: { key: Tab; label: string }[] = [
  { key: 'bills', label: 'Bills' },
  { key: 'payments', label: 'Payments' },
  { key: 'ageing', label: 'Ageing' },
];

export default function PayablesPage() {
  const [tab, setTab] = useState<Tab>('bills');

  // Bills state
  const [bills, setBills] = useState<BillResponse[]>([]);
  const [billLoading, setBillLoading] = useState(true);
  const [billError, setBillError] = useState<string | null>(null);

  // Payments state
  const [payments, setPayments] = useState<SupplierPaymentResponse[]>([]);
  const [payLoading, setPayLoading] = useState(true);
  const [payError, setPayError] = useState<string | null>(null);

  // Ageing state
  const [ageing, setAgeing] = useState<AgeingResponse | null>(null);
  const [ageingLoading, setAgeingLoading] = useState(true);
  const [ageingError, setAgeingError] = useState<string | null>(null);

  // Create bill modal
  const [billModal, setBillModal] = useState(false);
  const [billForm, setBillForm] = useState({
    supplier_id: '',
    lines: [{ description: '', qty: 1, unit_cost: 0 }] as BillLineRequest[],
  });
  const [billSaving, setBillSaving] = useState(false);
  const [billCreateError, setBillCreateError] = useState<string | null>(null);

  // Create payment modal
  const [payModal, setPayModal] = useState(false);
  const [payForm, setPayForm] = useState({
    supplier_id: '',
    amount: 0,
    payment_method: 'bank_transfer',
    reference: '',
    payment_date: todayISO(),
  });
  const [paySaving, setPaySaving] = useState(false);
  const [payCreateError, setPayCreateError] = useState<string | null>(null);

  // Allocate modal
  const [allocModal, setAllocModal] = useState(false);
  const [allocPaymentId, setAllocPaymentId] = useState<string | null>(null);
  const [allocBills, setAllocBills] = useState<BillResponse[]>([]);
  const [allocAmounts, setAllocAmounts] = useState<Record<string, number>>({});
  const [allocSaving, setAllocSaving] = useState(false);
  const [allocError, setAllocError] = useState<string | null>(null);

  const fetchBills = useCallback(async () => {
    setBillLoading(true);
    setBillError(null);
    try {
      const data = await listBills();
      setBills(data);
    } catch (e: any) {
      setBillError(e?.message || 'Failed to load bills.');
    } finally {
      setBillLoading(false);
    }
  }, []);

  const fetchPayments = useCallback(async () => {
    setPayLoading(true);
    setPayError(null);
    try {
      const data = await listSupplierPayments();
      setPayments(data);
    } catch (e: any) {
      setPayError(e?.message || 'Failed to load payments.');
    } finally {
      setPayLoading(false);
    }
  }, []);

  const fetchAgeing = useCallback(async () => {
    setAgeingLoading(true);
    setAgeingError(null);
    try {
      const data = await getAPAgeing();
      setAgeing(data);
    } catch (e: any) {
      setAgeingError(e?.message || 'Failed to load ageing.');
    } finally {
      setAgeingLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tab === 'bills') fetchBills();
    else if (tab === 'payments') fetchPayments();
    else fetchAgeing();
  }, [tab, fetchBills, fetchPayments, fetchAgeing]);

  // --- Bill actions ---

  async function submitBill(e: React.FormEvent) {
    e.preventDefault();
    const validLines = billForm.lines.filter((l) => l.description && l.qty > 0);
    if (!billForm.supplier_id.trim() || validLines.length === 0) return;
    setBillSaving(true);
    setBillCreateError(null);
    try {
      await createBill({
        supplier_id: billForm.supplier_id.trim(),
        posting_date: todayISO(),
        due_date: dueDateISO(),
        lines: validLines,
      });
      setBillModal(false);
      setBillForm({ supplier_id: '', lines: [{ description: '', qty: 1, unit_cost: 0 }] });
      await fetchBills();
    } catch (e: any) {
      setBillCreateError(e?.message || 'Failed to create bill.');
    } finally {
      setBillSaving(false);
    }
  }

  async function handleIssue(id: string) {
    try {
      await issueBill(id);
      await fetchBills();
    } catch (e: any) {
      setBillError(e?.message || 'Failed to issue bill.');
    }
  }

  async function handleVoid(id: string) {
    try {
      await voidBill(id);
      await fetchBills();
    } catch (e: any) {
      setBillError(e?.message || 'Failed to void bill.');
    }
  }

  // --- Payment actions ---

  async function submitPayment(e: React.FormEvent) {
    e.preventDefault();
    if (!payForm.supplier_id.trim() || payForm.amount <= 0) return;
    setPaySaving(true);
    setPayCreateError(null);
    try {
      await createSupplierPayment({
        supplier_id: payForm.supplier_id.trim(),
        payment_date: payForm.payment_date,
        amount: payForm.amount,
        payment_method: payForm.payment_method,
        reference: payForm.reference.trim() || null,
      });
      setPayModal(false);
      setPayForm({
        supplier_id: '',
        amount: 0,
        payment_method: 'bank_transfer',
        reference: '',
        payment_date: todayISO(),
      });
      await fetchPayments();
    } catch (e: any) {
      setPayCreateError(e?.message || 'Failed to record payment.');
    } finally {
      setPaySaving(false);
    }
  }

  async function openAllocate(paymentId: string) {
    setAllocPaymentId(paymentId);
    setAllocAmounts({});
    setAllocError(null);
    try {
      const data = await listBills({ status: 'issued' });
      setAllocBills(data);
    } catch {
      setAllocBills([]);
    }
    setAllocModal(true);
  }

  async function submitAllocate() {
    if (!allocPaymentId) return;
    const allocs = Object.entries(allocAmounts)
      .filter(([, amt]) => amt > 0)
      .map(([bill_id, amount]) => ({ bill_id, amount }));
    if (allocs.length === 0) return;
    setAllocSaving(true);
    setAllocError(null);
    try {
      // allocateBillPayment expects a single BillAllocationRequest or an array
      for (const req of allocs) {
        await allocateBillPayment(allocPaymentId, req);
      }
      setAllocModal(false);
      await fetchPayments();
      await fetchBills();
    } catch (e: any) {
      setAllocError(e?.message || 'Failed to allocate.');
    } finally {
      setAllocSaving(false);
    }
  }

  // --- Helpers ---

  function addBillLine() {
    setBillForm((prev) => ({
      ...prev,
      lines: [...prev.lines, { description: '', qty: 1, unit_cost: 0 }],
    }));
  }

  function removeBillLine(idx: number) {
    setBillForm((prev) => ({
      ...prev,
      lines: prev.lines.filter((_, i) => i !== idx),
    }));
  }

  function updateBillLine(idx: number, patch: Partial<BillLineRequest>) {
    setBillForm((prev) => {
      const next = [...prev.lines];
      next[idx] = { ...next[idx], ...patch };
      return { ...prev, lines: next };
    });
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Accounts Payable"
        description="Supplier bills, payments, and debit notes"
        actions={
          tab === 'bills' ? (
            <button
              onClick={() => {
                setBillCreateError(null);
                setBillModal(true);
              }}
              className="flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
            >
              <Plus className="h-4 w-4" />
              New Bill
            </button>
          ) : tab === 'payments' ? (
            <button
              onClick={() => {
                setPayCreateError(null);
                setPayModal(true);
              }}
              className="flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
            >
              <Plus className="h-4 w-4" />
              Record Payment
            </button>
          ) : null
        }
      />

      {/* Tabs */}
      <div className="flex gap-1 border-b">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              tab === t.key
                ? 'border-b-2 border-primary text-primary'
                : 'text-muted-foreground hover:text-accent-foreground'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Bills tab */}
      {tab === 'bills' ? (
        <div className="overflow-x-auto rounded-lg border bg-white">
          {billLoading ? (
            <div className="p-4">
              <SkeletonRows rows={8} />
            </div>
          ) : billError ? (
            <div className="p-4">
              <ErrorBox message={billError} onRetry={fetchBills} />
            </div>
          ) : bills.length === 0 ? (
            <p className="p-6 text-center text-sm text-muted-foreground">
              No bills found.
            </p>
          ) : (
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="border-b text-xs font-medium text-muted-foreground">
                <tr>
                  <th className="px-4 py-3">Bill No</th>
                  <th className="px-4 py-3">Supplier</th>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Due Date</th>
                  <th className="px-4 py-3 text-right">Total</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">PO Ref</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody>
                {bills.map((b) => (
                  <tr key={b.id} className="border-b hover:bg-muted">
                    <td className="px-4 py-3 font-mono text-xs">{b.bill_no}</td>
                    <td className="px-4 py-3 font-mono text-xs">{b.supplier_id}</td>
                    <td className="px-4 py-3">{fmtDate(b.posting_date)}</td>
                    <td className="px-4 py-3">{fmtDate(b.due_date)}</td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {b.total.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                          STATUS_COLORS[b.status] ?? 'bg-gray-100 text-gray-700'
                        }`}
                      >
                        {b.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">
                      {b.po_id || '—'}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-1">
                        {b.status === 'draft' ? (
                          <button
                            onClick={() => handleIssue(b.id)}
                            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-green-700 hover:bg-green-50"
                          >
                            <CheckCircle className="h-3 w-3" />
                            Issue
                          </button>
                        ) : null}
                        {(b.status === 'draft' || b.status === 'issued') ? (
                          <button
                            onClick={() => handleVoid(b.id)}
                            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50"
                          >
                            <Ban className="h-3 w-3" />
                            Void
                          </button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ) : null}

      {/* Payments tab */}
      {tab === 'payments' ? (
        <div className="overflow-x-auto rounded-lg border bg-white">
          {payLoading ? (
            <div className="p-4">
              <SkeletonRows rows={8} />
            </div>
          ) : payError ? (
            <div className="p-4">
              <ErrorBox message={payError} onRetry={fetchPayments} />
            </div>
          ) : payments.length === 0 ? (
            <p className="p-6 text-center text-sm text-muted-foreground">
              No payments found.
            </p>
          ) : (
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="border-b text-xs font-medium text-muted-foreground">
                <tr>
                  <th className="px-4 py-3">Payment No</th>
                  <th className="px-4 py-3">Supplier</th>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3 text-right">Amount</th>
                  <th className="px-4 py-3">Method</th>
                  <th className="px-4 py-3">Reference</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody>
                {payments.map((p) => (
                  <tr key={p.id} className="border-b hover:bg-muted">
                    <td className="px-4 py-3 font-mono text-xs">{p.payment_no}</td>
                    <td className="px-4 py-3 font-mono text-xs">{p.supplier_id}</td>
                    <td className="px-4 py-3">{fmtDate(p.payment_date)}</td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {p.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </td>
                    <td className="px-4 py-3 text-xs capitalize">
                      {(p.payment_method || '').replace(/_/g, ' ')}
                    </td>
                    <td className="px-4 py-3">{p.reference || '—'}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                          STATUS_COLORS[p.status] ?? 'bg-gray-100 text-gray-700'
                        }`}
                      >
                        {p.status}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {p.status === 'unallocated' || p.status === 'partial' ? (
                        <button
                          onClick={() => openAllocate(p.id)}
                          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-blue-700 hover:bg-blue-50"
                        >
                          <Link2 className="h-3 w-3" />
                          Allocate
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ) : null}

      {/* Ageing tab */}
      {tab === 'ageing' ? (
        <div className="rounded-lg border bg-white p-6">
          {ageingLoading ? (
            <SkeletonRows rows={5} />
          ) : ageingError ? (
            <ErrorBox message={ageingError} onRetry={fetchAgeing} />
          ) : ageing ? (
            <div className="space-y-6">
              <div className="flex flex-wrap gap-4">
                {ageing.buckets.map((b) => (
                  <div
                    key={b.label}
                    className="flex-1 rounded-lg border p-4 text-center min-w-[120px]"
                  >
                    <p className="text-xs font-medium text-muted-foreground">{b.label}</p>
                    <p className="mt-1 text-lg font-semibold">{b.count}</p>
                    <p className="text-sm text-muted-foreground">
                      {b.total.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </p>
                  </div>
                ))}
              </div>
              <div className="rounded-md bg-muted p-4 text-sm">
                <span className="font-medium">Total Outstanding: </span>
                {ageing.total_outstanding.toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                })}
              </div>
            </div>
          ) : (
            <p className="text-center text-sm text-muted-foreground">No ageing data.</p>
          )}
        </div>
      ) : null}

      {/* Create Bill Modal */}
      <Modal
        open={billModal}
        onClose={() => setBillModal(false)}
        title="New Bill"
        maxWidth="max-w-lg"
      >
        <form onSubmit={submitBill} className="space-y-4 text-sm">
          {billCreateError ? <ErrorBox message={billCreateError} /> : null}
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Supplier ID</label>
            <input
              value={billForm.supplier_id}
              onChange={(e) => setBillForm({ ...billForm, supplier_id: e.target.value })}
              required
              placeholder="UUID of contact"
              className="w-full rounded-md border px-3 py-1.5 text-sm"
            />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-xs font-medium text-muted-foreground">Line Items</label>
              <button
                type="button"
                onClick={addBillLine}
                className="text-xs text-primary underline"
              >
                + Add line
              </button>
            </div>
            {billForm.lines.map((line, idx) => (
              <div key={idx} className="grid grid-cols-12 gap-2 rounded-md border p-3">
                <div className="col-span-5 space-y-1">
                  <label className="text-[10px] font-medium text-muted-foreground">Description</label>
                  <input
                    value={line.description}
                    onChange={(e) => updateBillLine(idx, { description: e.target.value })}
                    className="w-full rounded-md border px-2 py-1 text-xs"
                  />
                </div>
                <div className="col-span-2 space-y-1">
                  <label className="text-[10px] font-medium text-muted-foreground">Qty</label>
                  <input
                    type="number"
                    step="1"
                    min="1"
                    value={line.qty}
                    onChange={(e) =>
                      updateBillLine(idx, { qty: parseInt(e.target.value) || 1 })
                    }
                    className="w-full rounded-md border px-2 py-1 text-xs"
                  />
                </div>
                <div className="col-span-3 space-y-1">
                  <label className="text-[10px] font-medium text-muted-foreground">Unit Cost</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={line.unit_cost || ''}
                    onChange={(e) =>
                      updateBillLine(idx, { unit_cost: parseFloat(e.target.value) || 0 })
                    }
                    className="w-full rounded-md border px-2 py-1 text-xs"
                  />
                </div>
                <div className="col-span-2 space-y-1">
                  <label className="text-[10px] font-medium text-muted-foreground">Total</label>
                  <p className="py-1 text-xs tabular-nums text-muted-foreground">
                    {(line.qty * line.unit_cost).toLocaleString(undefined, {
                      minimumFractionDigits: 2,
                    })}
                  </p>
                </div>
                {billForm.lines.length > 1 ? (
                  <div className="col-span-0 flex items-end">
                    <button
                      type="button"
                      onClick={() => removeBillLine(idx)}
                      className="rounded-md px-1 py-1 text-xs text-red-600 hover:bg-red-50"
                    >
                      X
                    </button>
                  </div>
                ) : null}
              </div>
            ))}
          </div>

          <button
            type="submit"
            disabled={
              billSaving ||
              !billForm.supplier_id.trim() ||
              billForm.lines.filter((l) => l.description && l.qty > 0).length === 0
            }
            className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-60"
          >
            {billSaving ? <Spinner className="text-primary-foreground" /> : null}
            Create Bill
          </button>
        </form>
      </Modal>

      {/* Record Payment Modal */}
      <Modal
        open={payModal}
        onClose={() => setPayModal(false)}
        title="Record Supplier Payment"
        maxWidth="max-w-md"
      >
        <form onSubmit={submitPayment} className="space-y-4 text-sm">
          {payCreateError ? <ErrorBox message={payCreateError} /> : null}
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Supplier ID</label>
            <input
              value={payForm.supplier_id}
              onChange={(e) => setPayForm({ ...payForm, supplier_id: e.target.value })}
              required
              placeholder="UUID of contact"
              className="w-full rounded-md border px-3 py-1.5 text-sm"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Payment Date</label>
              <input
                type="date"
                value={payForm.payment_date}
                onChange={(e) => setPayForm({ ...payForm, payment_date: e.target.value })}
                className="w-full rounded-md border px-3 py-1.5 text-sm"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Amount</label>
              <input
                type="number"
                step="0.01"
                min="0.01"
                value={payForm.amount || ''}
                onChange={(e) =>
                  setPayForm({ ...payForm, amount: parseFloat(e.target.value) || 0 })
                }
                required
                className="w-full rounded-md border px-3 py-1.5 text-sm"
              />
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Payment Method</label>
            <select
              value={payForm.payment_method}
              onChange={(e) => setPayForm({ ...payForm, payment_method: e.target.value })}
              className="w-full rounded-md border px-3 py-1.5 text-sm"
            >
              {PAYMENT_METHODS.map((m) => (
                <option key={m} value={m}>
                  {m.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Reference</label>
            <input
              value={payForm.reference}
              onChange={(e) => setPayForm({ ...payForm, reference: e.target.value })}
              placeholder="Cheque no, transaction ID..."
              className="w-full rounded-md border px-3 py-1.5 text-sm"
            />
          </div>
          <button
            type="submit"
            disabled={paySaving || !payForm.supplier_id.trim() || payForm.amount <= 0}
            className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-60"
          >
            {paySaving ? <Spinner className="text-primary-foreground" /> : null}
            Record Payment
          </button>
        </form>
      </Modal>

      {/* Allocate Payment Modal */}
      <Modal
        open={allocModal}
        onClose={() => setAllocModal(false)}
        title="Allocate Payment to Bills"
        maxWidth="max-w-lg"
      >
        <div className="space-y-4 text-sm">
          {allocError ? <ErrorBox message={allocError} /> : null}
          <p className="text-xs text-muted-foreground">
            Select bills and amounts to allocate.
          </p>
          {allocBills.length === 0 ? (
            <p className="text-xs text-muted-foreground">No issued bills available.</p>
          ) : (
            <div className="space-y-2">
              {allocBills.map((b) => (
                <div key={b.id} className="flex items-center gap-3 rounded-md border p-3">
                  <div className="flex-1">
                    <p className="text-xs font-mono">{b.bill_no}</p>
                    <p className="text-[10px] text-muted-foreground">
                      {fmtDate(b.due_date)} ·{' '}
                      {b.total.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </p>
                  </div>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    max={b.total}
                    placeholder="Amount"
                    value={allocAmounts[b.id] || ''}
                    onChange={(e) =>
                      setAllocAmounts({
                        ...allocAmounts,
                        [b.id]: parseFloat(e.target.value) || 0,
                      })
                    }
                    className="w-32 rounded-md border px-2 py-1 text-xs"
                  />
                </div>
              ))}
            </div>
          )}
          <button
            onClick={submitAllocate}
            disabled={
              allocSaving ||
              Object.values(allocAmounts).filter((a) => a > 0).length === 0
            }
            className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-60"
          >
            {allocSaving ? <Spinner className="text-primary-foreground" /> : null}
            Allocate
          </button>
        </div>
      </Modal>
    </div>
  );
}
