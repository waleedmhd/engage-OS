'use client';

import { useCallback, useEffect, useState } from 'react';
import clsx from 'clsx';
import { useAuth } from '@/hooks/useAuth';
import { PageHeader } from '@/components/shared/PageHeader';
import { ErrorBox, Spinner } from '@/components/shared/ui';
import { listSalesOrders, listDispatches, confirmDispatch } from '@/lib/erp';
import type { DispatchResponse, SalesOrderResponse } from '@/types/api';

const STATUS_BADGES: Record<string, string> = {
  draft: 'bg-gray-100 text-gray-700',
  issued: 'bg-blue-100 text-blue-700',
  confirmed: 'bg-green-100 text-green-700',
  shipped: 'bg-blue-100 text-blue-700',
  delivered: 'bg-green-100 text-green-700',
  cancelled: 'bg-red-100 text-red-700',
  closed: 'bg-emerald-100 text-emerald-700',
};

type TabKey = 'so' | 'dispatch';

export default function FulfilmentPage() {
  const { user, isLoading: authLoading } = useAuth();
  const [tab, setTab] = useState<TabKey>('so');
  const [sos, setSos] = useState<SalesOrderResponse[]>([]);
  const [dispatches, setDispatches] = useState<DispatchResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [expandedSo, setExpandedSo] = useState<string | null>(null);
  const [expandedDispatch, setExpandedDispatch] = useState<string | null>(null);
  const [confirmingDispatch, setConfirmingDispatch] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [sosData, dispatchData] = await Promise.all([
        listSalesOrders(),
        listDispatches(),
      ]);
      setSos(sosData);
      setDispatches(dispatchData);
    } catch (e: any) {
      setError(e?.message || 'Failed to load fulfilment data.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  async function handleConfirmDispatch(dispatchId: string) {
    setConfirmingDispatch(dispatchId);
    try {
      await confirmDispatch(dispatchId);
      await fetchData();
    } catch (e: any) {
      setError(e?.message || 'Failed to confirm dispatch.');
    } finally {
      setConfirmingDispatch(null);
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
        title="Fulfilment"
        description="Sales orders and dispatches"
      />

      {/* Tabs */}
      <div className="flex gap-1 border-b pb-0">
        <button
          onClick={() => setTab('so')}
          className={clsx(
            'px-4 py-2 text-sm font-medium',
            tab === 'so'
              ? 'border-b-2 border-primary text-primary'
              : 'text-muted-foreground',
          )}
        >
          Sales Orders
        </button>
        <button
          onClick={() => setTab('dispatch')}
          className={clsx(
            'px-4 py-2 text-sm font-medium',
            tab === 'dispatch'
              ? 'border-b-2 border-primary text-primary'
              : 'text-muted-foreground',
          )}
        >
          Dispatches
        </button>
      </div>

      {/* Sales Orders Tab */}
      {tab === 'so' ? (
        <div className="overflow-x-auto rounded-lg border bg-white">
          <table className="w-full text-sm">
            <thead className="border-b text-left text-xs font-medium text-muted-foreground">
              <tr>
                <th className="px-4 py-3">SO No</th>
                <th className="px-4 py-3">Customer</th>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3 text-right">Lines</th>
              </tr>
            </thead>
            <tbody>
              {sos.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                    No sales orders found.
                  </td>
                </tr>
              ) : (
                sos.map((so) => (
                  <>
                    <tr
                      key={so.id}
                      onClick={() => setExpandedSo(expandedSo === so.id ? null : so.id)}
                      className="cursor-pointer border-b hover:bg-muted"
                    >
                      <td className="px-4 py-3 font-mono text-xs">{so.so_no}</td>
                      <td className="px-4 py-3 font-mono text-xs">
                        {so.customer_id.slice(0, 8)}
                      </td>
                      <td className="px-4 py-3">{fmt(so.order_date)}</td>
                      <td className="px-4 py-3">
                        <span
                          className={clsx(
                            'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
                            badgeStyle(so.status),
                          )}
                        >
                          {so.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">{so.lines.length}</td>
                    </tr>
                    {expandedSo === so.id ? (
                      <tr key={`${so.id}-lines`} className="bg-muted/30">
                        <td colSpan={5} className="px-6 py-4">
                          <p className="text-xs font-medium text-muted-foreground mb-2">
                            Lines
                          </p>
                          <table className="w-full text-xs">
                            <thead className="border-b text-left text-muted-foreground">
                              <tr>
                                <th className="py-1">Description</th>
                                <th className="py-1 text-right">Qty</th>
                                <th className="py-1 text-right">Unit Price</th>
                                <th className="py-1 text-right">Total</th>
                              </tr>
                            </thead>
                            <tbody>
                              {so.lines.map((l) => (
                                <tr key={l.id} className="border-b">
                                  <td className="py-1">{l.description}</td>
                                  <td className="py-1 text-right">{l.qty}</td>
                                  <td className="py-1 text-right">
                                    AED {Number(l.unit_price).toFixed(2)}
                                  </td>
                                  <td className="py-1 text-right">
                                    AED {Number(l.line_total).toFixed(2)}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          <p className="mt-1 text-xs text-muted-foreground">
                            Currency: {so.currency_code}
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

      {/* Dispatches Tab */}
      {tab === 'dispatch' ? (
        <div className="overflow-x-auto rounded-lg border bg-white">
          <table className="w-full text-sm">
            <thead className="border-b text-left text-xs font-medium text-muted-foreground">
              <tr>
                <th className="px-4 py-3">Dispatch No</th>
                <th className="px-4 py-3">SO Ref</th>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {dispatches.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                    No dispatches found.
                  </td>
                </tr>
              ) : (
                dispatches.map((dp) => (
                  <>
                    <tr
                      key={dp.id}
                      onClick={() =>
                        setExpandedDispatch(expandedDispatch === dp.id ? null : dp.id)
                      }
                      className="cursor-pointer border-b hover:bg-muted"
                    >
                      <td className="px-4 py-3 font-mono text-xs">{dp.dispatch_no}</td>
                      <td className="px-4 py-3 font-mono text-xs">
                        {dp.so_id ? dp.so_id.slice(0, 8) : '—'}
                      </td>
                      <td className="px-4 py-3">{fmt(dp.dispatch_date)}</td>
                      <td className="px-4 py-3">
                        <span
                          className={clsx(
                            'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
                            badgeStyle(dp.status),
                          )}
                        >
                          {dp.status}
                        </span>
                      </td>
                      <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                        {dp.status === 'draft' ? (
                          <button
                            onClick={() => handleConfirmDispatch(dp.id)}
                            disabled={confirmingDispatch === dp.id}
                            className="rounded-md bg-primary px-2 py-1 text-xs text-primary-foreground disabled:opacity-60"
                          >
                            {confirmingDispatch === dp.id ? (
                              <Spinner className="text-primary-foreground h-3 w-3" />
                            ) : null}
                            Confirm
                          </button>
                        ) : null}
                      </td>
                    </tr>
                    {expandedDispatch === dp.id ? (
                      <tr key={`${dp.id}-lines`} className="bg-muted/30">
                        <td colSpan={5} className="px-6 py-4">
                          <p className="text-xs font-medium text-muted-foreground mb-2">
                            Dispatched Items
                          </p>
                          <table className="w-full text-xs">
                            <thead className="border-b text-left text-muted-foreground">
                              <tr>
                                <th className="py-1">Stock Unit</th>
                                <th className="py-1 text-right">Qty</th>
                                <th className="py-1 text-right">Unit Cost</th>
                              </tr>
                            </thead>
                            <tbody>
                              {dp.lines.map((l) => (
                                <tr key={l.id} className="border-b">
                                  <td className="py-1 font-mono">
                                    {l.stock_unit_id
                                      ? l.stock_unit_id.slice(0, 8)
                                      : '—'}
                                  </td>
                                  <td className="py-1 text-right">{l.qty}</td>
                                  <td className="py-1 text-right">
                                    AED {Number(l.unit_cost).toFixed(2)}
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
