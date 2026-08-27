'use client';

import { useCallback, useEffect, useState } from 'react';
import clsx from 'clsx';
import { useAuth } from '@/hooks/useAuth';
import { PageHeader } from '@/components/shared/PageHeader';
import { ErrorBox, Spinner } from '@/components/shared/ui';
import { listStock, getStockValuation, getSerial } from '@/lib/erp';
import type { SerialLookupResponse, StockOnHandResponse, StockValuationResponse } from '@/types/api';

const STATUS_BADGES: Record<string, string> = {
  IN_STOCK: 'bg-green-100 text-green-700',
  in_stock: 'bg-green-100 text-green-700',
  SOLD: 'bg-gray-100 text-gray-700',
  sold: 'bg-gray-100 text-gray-700',
  ON_ORDER: 'bg-blue-100 text-blue-700',
  on_order: 'bg-blue-100 text-blue-700',
  IN_TRANSIT: 'bg-amber-100 text-amber-700',
  in_transit: 'bg-amber-100 text-amber-700',
  SCRAPPED: 'bg-red-100 text-red-700',
  scrapped: 'bg-red-100 text-red-700',
};

export default function InventoryStockPage() {
  const { user, isLoading: authLoading } = useAuth();
  const [stock, setStock] = useState<StockOnHandResponse[]>([]);
  const [valuation, setValuation] = useState<StockValuationResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Serial lookup state
  const [serialInput, setSerialInput] = useState('');
  const [serialResult, setSerialResult] = useState<SerialLookupResponse | null>(null);
  const [serialLoading, setSerialLoading] = useState(false);
  const [serialError, setSerialError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [stockData, valData] = await Promise.all([
        listStock(),
        getStockValuation(),
      ]);
      setStock(stockData);
      setValuation(valData);
    } catch (e: any) {
      setError(e?.message || 'Failed to load stock data.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  async function lookupSerial() {
    const s = serialInput.trim();
    if (!s) return;
    setSerialLoading(true);
    setSerialError(null);
    setSerialResult(null);
    try {
      const result = await getSerial(s);
      setSerialResult(result);
    } catch (e: any) {
      setSerialError(e?.message || 'Serial not found.');
    } finally {
      setSerialLoading(false);
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
        title="Stock"
        description="Stock on hand, serial lookup, adjustments"
      />

      {/* Valuation Summary Cards */}
      {valuation ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div className="rounded-lg border p-4">
            <p className="text-xs text-muted-foreground">Total Value</p>
            <p className="text-lg font-semibold">
              AED {Number(valuation.total_value).toFixed(2)}
            </p>
          </div>
          <div className="rounded-lg border p-4">
            <p className="text-xs text-muted-foreground">Item Count</p>
            <p className="text-lg font-semibold">{valuation.item_count}</p>
          </div>
          <div className="rounded-lg border p-4">
            <p className="text-xs text-muted-foreground">Serialized Value</p>
            <p className="text-lg font-semibold">
              AED {Number(valuation.serialized_value).toFixed(2)}
            </p>
          </div>
          <div className="rounded-lg border p-4">
            <p className="text-xs text-muted-foreground">Bulk Value</p>
            <p className="text-lg font-semibold">
              AED {Number(valuation.bulk_value).toFixed(2)}
            </p>
          </div>
        </div>
      ) : null}

      {/* Stock on Hand Table */}
      <div className="rounded-lg border bg-white p-6">
        <h2 className="text-sm font-semibold">Stock on Hand</h2>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b text-left text-xs font-medium text-muted-foreground">
              <tr>
                <th className="px-3 py-3">Item</th>
                <th className="px-3 py-3">Location</th>
                <th className="px-3 py-3 text-right">Qty</th>
                <th className="px-3 py-3 text-right">Value</th>
              </tr>
            </thead>
            <tbody>
              {stock.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-3 py-8 text-center text-muted-foreground">
                    No stock on hand.
                  </td>
                </tr>
              ) : (
                stock.map((s, i) => (
                  <tr key={`${s.item_id}-${s.location_id || i}`} className="border-b">
                    <td className="px-3 py-3">{s.item_name}</td>
                    <td className="px-3 py-3 font-mono text-xs">
                      {s.location_code || '—'}
                    </td>
                    <td className="px-3 py-3 text-right">{s.qty}</td>
                    <td className="px-3 py-3 text-right">
                      AED {Number(s.value).toFixed(2)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Serial Lookup */}
      <div className="rounded-lg border bg-white p-6">
        <h2 className="text-sm font-semibold">Serial Lookup</h2>
        <div className="mt-3 flex gap-2">
          <input
            value={serialInput}
            onChange={(e) => setSerialInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') lookupSerial(); }}
            placeholder="Enter serial number..."
            className="rounded-md border px-3 py-1.5 text-sm w-full max-w-xs"
          />
          <button
            onClick={lookupSerial}
            disabled={serialLoading || !serialInput.trim()}
            className="rounded-md bg-primary px-4 py-1.5 text-sm text-primary-foreground disabled:opacity-60"
          >
            {serialLoading ? <Spinner className="text-primary-foreground" /> : null}
            Search
          </button>
        </div>

        {serialError ? (
          <p className="mt-3 text-sm text-red-600">{serialError}</p>
        ) : null}

        {serialResult ? (
          <div className="mt-4 rounded-lg border p-4">
            <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
              <div>
                <p className="text-xs text-muted-foreground">Serial</p>
                <p className="font-mono">{serialResult.serial_no}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Item</p>
                <p>{serialResult.item_name || serialResult.item_id || '—'}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Status</p>
                <span
                  className={clsx(
                    'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
                    badgeStyle(serialResult.status),
                  )}
                >
                  {serialResult.status}
                </span>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Location</p>
                <p>{serialResult.location || '—'}</p>
              </div>
            </div>

            {serialResult.lifecycle.length > 0 ? (
              <div className="mt-4 border-t pt-4">
                <p className="text-xs font-medium text-muted-foreground">Lifecycle Movements</p>
                <table className="mt-2 w-full text-xs">
                  <thead className="border-b text-left text-muted-foreground">
                    <tr>
                      <th className="py-1">Date</th>
                      <th className="py-1">Type</th>
                      <th className="py-1 text-right">Qty Change</th>
                      <th className="py-1 text-right">Rate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {serialResult.lifecycle.map((m, i) => (
                      <tr key={i} className="border-b">
                        <td className="py-1">{m.posting_date}</td>
                        <td className="py-1">{m.voucher_type}</td>
                        <td className="py-1 text-right">{Number(m.qty_change)}</td>
                        <td className="py-1 text-right">
                          AED {Number(m.valuation_rate).toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
