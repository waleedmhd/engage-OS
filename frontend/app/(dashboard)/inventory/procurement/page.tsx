'use client';

import { useCallback, useEffect, useState } from 'react';
import clsx from 'clsx';
import { useAuth } from '@/hooks/useAuth';
import { PageHeader } from '@/components/shared/PageHeader';
import { ErrorBox, Spinner } from '@/components/shared/ui';
import { listPurchaseOrders, listGRNs, confirmGRN } from '@/lib/erp';
import type { GRNResponse, PurchaseOrderResponse } from '@/types/api';

const STATUS_BADGES: Record<string, string> = {
  draft: 'bg-gray-100 text-gray-700',
  issued: 'bg-blue-100 text-blue-700',
  received: 'bg-green-100 text-green-700',
  confirmed: 'bg-green-100 text-green-700',
  cancelled: 'bg-red-100 text-red-700',
  closed: 'bg-emerald-100 text-emerald-700',
};

type TabKey = 'po' | 'grn';

export default function ProcurementPage() {
  const { user, isLoading: authLoading } = useAuth();
  const [tab, setTab] = useState<TabKey>('po');
  const [pos, setPos] = useState<PurchaseOrderResponse[]>([]);
  const [grns, setGrns] = useState<GRNResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Expand / confirm states
  const [expandedPo, setExpandedPo] = useState<string | null>(null);
  const [expandedGrn, setExpandedGrn] = useState<string | null>(null);
  const [confirmingGrn, setConfirmingGrn] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [posData, grnsData] = await Promise.all([
        listPurchaseOrders(),
        listGRNs(),
      ]);
      setPos(posData);
      setGrns(grnsData);
    } catch (e: any) {
      setError(e?.message || 'Failed to load procurement data.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  async function handleConfirmGrn(grnId: string) {
    setConfirmingGrn(grnId);
    try {
      await confirmGRN(grnId);
      await fetchData();
    } catch (e: any) {
      setError(e?.message || 'Failed to confirm GRN.');
    } finally {
      setConfirmingGrn(null);
    }
  }

  function badgeStyle(status: string): string {
    return STATUS_BADGES[status] || 'bg-gray-100 text-gray-700';
  }

  if (authLoading || loading) return <Spinner />;
  if (error) return <ErrorBox message={error} onRetry={fetchData} />;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Procurement"
        description="Purchase orders and goods receipts"
      />

      {/* Tabs */}
      <div className="flex gap-1 border-b pb-0">
        <button
          onClick={() => setTab('po')}
          className={clsx(
            'px-4 py-2 text-sm font-medium',
            tab === 'po'
              ? 'border-b-2 border-primary text-primary'
              : 'text-muted-foreground',
          )}
        >
          Purchase Orders
        </button>
        <button
          onClick={() => setTab('grn')}
          className={clsx(
            'px-4 py-2 text-sm font-medium',
            tab === 'grn'
              ? 'border-b-2 border-primary text-primary'
              : 'text-muted-foreground',
          )}
        >
          Goods Receipts
        </button>
      </div>

      {/* Purchase Orders Tab */}
      {tab === 'po' ? (
        <div className="overflow-x-auto rounded-lg border bg-white">
          <table className="w-full text-sm">
            <thead className="border-b text-left text-xs font-medium text-muted-foreground">
              <tr>
                <th className="px-4 py-3">PO No</th>
                <th className="px-4 py-3">Supplier</th>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Expected Date</th>
              </tr>
            </thead>
            <tbody>
              {pos.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                    No purchase orders found.
                  </td>
                </tr>
              ) : (
                pos.map((po) => (
                  <>
                    <tr
                      key={po.id}
                      onClick={() => setExpandedPo(expandedPo === po.id ? null : po.id)}
                      className="cursor-pointer border-b hover:bg-muted"
                    >
                      <td className="px-4 py-3 font-mono text-xs">{po.po_no}</td>
                      <td className="px-4 py-3 font-mono text-xs">{po.supplier_id.slice(0, 8)}</td>
                      <td className="px-4 py-3">{fmt(po.order_date)}</td>
                      <td className="px-4 py-3">
                        <span
                          className={clsx(
                            'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
                            badgeStyle(po.status),
                          )}
                        >
                          {po.status}
                        </span>
                      </td>
                      <td className="px-4 py-3">{fmt(po.expected_date)}</td>
                    </tr>
                    {expandedPo === po.id ? (
                      <tr key={`${po.id}-lines`} className="bg-muted/30">
                        <td colSpan={5} className="px-6 py-4">
                          <p className="text-xs font-medium text-muted-foreground mb-2">
                            Lines
                          </p>
                          <table className="w-full text-xs">
                            <thead className="border-b text-left text-muted-foreground">
                              <tr>
                                <th className="py-1">Description</th>
                                <th className="py-1 text-right">Qty</th>
                                <th className="py-1 text-right">Unit Cost</th>
                                <th className="py-1 text-right">Total</th>
                              </tr>
                            </thead>
                            <tbody>
                              {po.lines.map((l) => (
                                <tr key={l.id} className="border-b">
                                  <td className="py-1">{l.description}</td>
                                  <td className="py-1 text-right">{l.qty}</td>
                                  <td className="py-1 text-right">
                                    AED {Number(l.unit_cost).toFixed(2)}
                                  </td>
                                  <td className="py-1 text-right">
                                    AED {Number(l.line_total).toFixed(2)}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          <p className="mt-1 text-xs text-muted-foreground">
                            Currency: {po.currency_code}
                            {po.remarks ? ` | Remarks: ${po.remarks}` : ''}
                          </p>
                        </td>
                      </tr>
                    ) : null}
                  </>
                ))
              )}
            </tbody>
          </table>
        </div>
      ) : null}

      {/* GRN Tab */}
      {tab === 'grn' ? (
        <div className="overflow-x-auto rounded-lg border bg-white">
          <table className="w-full text-sm">
            <thead className="border-b text-left text-xs font-medium text-muted-foreground">
              <tr>
                <th className="px-4 py-3">GRN No</th>
                <th className="px-4 py-3">PO Ref</th>
                <th className="px-4 py-3">Warehouse</th>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {grns.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                    No goods receipts found.
                  </td>
                </tr>
              ) : (
                grns.map((grn) => (
                  <>
                    <tr
                      key={grn.id}
                      onClick={() => setExpandedGrn(expandedGrn === grn.id ? null : grn.id)}
                      className="cursor-pointer border-b hover:bg-muted"
                    >
                      <td className="px-4 py-3 font-mono text-xs">{grn.grn_no}</td>
                      <td className="px-4 py-3 font-mono text-xs">
                        {grn.po_id ? grn.po_id.slice(0, 8) : '—'}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs">
                        {grn.warehouse_id.slice(0, 8)}
                      </td>
                      <td className="px-4 py-3">{fmt(grn.receipt_date)}</td>
                      <td className="px-4 py-3">
                        <span
                          className={clsx(
                            'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
                            badgeStyle(grn.status),
                          )}
                        >
                          {grn.status}
                        </span>
                      </td>
                      <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                        {grn.status === 'draft' ? (
                          <button
                            onClick={() => handleConfirmGrn(grn.id)}
                            disabled={confirmingGrn === grn.id}
                            className="rounded-md bg-primary px-2 py-1 text-xs text-primary-foreground disabled:opacity-60"
                          >
                            {confirmingGrn === grn.id ? (
                              <Spinner className="text-primary-foreground h-3 w-3" />
                            ) : null}
                            Confirm
                          </button>
                        ) : null}
                      </td>
                    </tr>
                    {expandedGrn === grn.id ? (
                      <tr key={`${grn.id}-lines`} className="bg-muted/30">
                        <td colSpan={6} className="px-6 py-4">
                          <p className="text-xs font-medium text-muted-foreground mb-2">
                            Lines
                          </p>
                          <table className="w-full text-xs">
                            <thead className="border-b text-left text-muted-foreground">
                              <tr>
                                <th className="py-1">Serial</th>
                                <th className="py-1 text-right">Qty Received</th>
                                <th className="py-1 text-right">Unit Cost</th>
                                <th className="py-1 text-right">Total</th>
                              </tr>
                            </thead>
                            <tbody>
                              {grn.lines.map((l) => (
                                <tr key={l.id} className="border-b">
                                  <td className="py-1 font-mono">
                                    {l.serial_no || '—'}
                                  </td>
                                  <td className="py-1 text-right">{l.qty_received}</td>
                                  <td className="py-1 text-right">
                                    AED {Number(l.unit_cost).toFixed(2)}
                                  </td>
                                  <td className="py-1 text-right">
                                    AED {Number(l.line_total).toFixed(2)}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </td>
                      </tr>
                    ) : null}
                  </>
                ))
              )}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

function fmt(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
}
