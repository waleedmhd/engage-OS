'use client';

import { useState, useEffect } from 'react';
import { getContactErpSummary } from '@/lib/erp';
import type { ContactErpSummary } from '@/types/api';
import { Spinner } from '@/components/shared/ui';

export function ErpSummary({ contactId }: { contactId: string }) {
  const [data, setData] = useState<ContactErpSummary | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    getContactErpSummary(contactId)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [contactId]);

  if (loading) return <Spinner />;
  if (!data) return (
    <p className="text-sm text-muted-foreground">No ERP data for this contact.</p>
  );

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-lg border p-3">
          <p className="text-xs text-muted-foreground">Outstanding AR</p>
          <p className="text-lg font-semibold">
            AED {data.outstanding_balance.toFixed(2)}
          </p>
        </div>
        <div className="rounded-lg border p-3">
          <p className="text-xs text-muted-foreground">Total Revenue</p>
          <p className="text-lg font-semibold">
            AED {data.total_revenue.toFixed(2)}
          </p>
        </div>
      </div>
      {data.recent_invoices.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-medium text-muted-foreground">
            Recent Invoices
          </p>
          <ul className="space-y-1">
            {data.recent_invoices.map((inv) => (
              <li
                key={inv.id}
                className="flex justify-between rounded border px-3 py-1.5 text-sm"
              >
                <span>{inv.invoice_no}</span>
                <span className="font-medium">
                  AED {inv.total.toFixed(2)}
                </span>
                <span className="text-xs text-muted-foreground">{inv.status}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
