'use client';

import { useEffect, useState } from 'react';
import { authedFetch } from '@/lib/authedFetch';
import type { ContactIntelligenceResponse } from '@/types/api';

type Props = { contactId: string };

export function MarketIntelligence({ contactId }: Props) {
  const [data, setData] = useState<ContactIntelligenceResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    authedFetch<ContactIntelligenceResponse>(
      `/market/contacts/${contactId}/intelligence`,
    )
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [contactId]);

  if (loading) {
    return <p className="text-sm text-muted-foreground">Loading...</p>;
  }

  if (!data) {
    return <p className="text-sm text-muted-foreground">No market data available.</p>;
  }

  if (data.total_messages === 0) {
    return <p className="text-sm text-muted-foreground">No market messages for this contact.</p>;
  }

  const prefs = data.attribute_preferences;
  const price = data.price_range;

  return (
    <div className="space-y-4">
      {/* Stat row */}
      <div className="flex items-center gap-3 text-sm">
        <span className="font-medium tabular-nums">{data.total_messages}</span>
        <span className="text-muted-foreground">messages</span>
        <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
          {data.buy_messages} WTB
        </span>
        <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">
          {data.sell_messages} WTS
        </span>
      </div>

      {/* Price range */}
      <div>
        <p className="text-xs text-muted-foreground">Price Range</p>
        <p className="text-sm font-medium tabular-nums">
          {price.min_unit_price != null || price.max_unit_price != null ? (
            <>
              {price.currency ?? 'AED'}{' '}
              {price.min_unit_price != null ? Number(price.min_unit_price).toLocaleString() : '?'}
              {' – '}
              {price.max_unit_price != null ? Number(price.max_unit_price).toLocaleString() : '?'}
            </>
          ) : (
            'No price data'
          )}
        </p>
      </div>

      {/* Product interests */}
      {data.products.length > 0 ? (
        <div>
          <p className="text-xs text-muted-foreground">Products</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {data.products.map((p) => (
              <span
                key={p.product_id}
                className="inline-flex items-center gap-1 rounded-full border bg-white px-2.5 py-0.5 text-xs"
              >
                {p.product_name}
                <span className="text-blue-600">+{p.buy_count}</span>
                <span className="text-muted-foreground">/</span>
                <span className="text-amber-600">+{p.sell_count}</span>
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {/* Attribute preferences: top 5 per category */}
      {(['storage', 'ram', 'color', 'region', 'condition'] as const).map((cat) => {
        const items = prefs[cat] ?? [];
        if (items.length === 0) return null;
        return (
          <div key={cat}>
            <p className="text-xs capitalize text-muted-foreground">{cat}</p>
            <div className="mt-1 flex flex-wrap gap-1">
              {items.slice(0, 5).map((item) => (
                <span
                  key={item.value}
                  className="inline-flex items-center rounded border bg-gray-50 px-2 py-0.5 text-xs"
                >
                  {item.value}
                  <span className="ml-1 text-muted-foreground">\xD7{item.count}</span>
                </span>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
