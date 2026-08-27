'use client';

import { useCallback, useEffect, useState } from 'react';
import clsx from 'clsx';
import { useAuth } from '@/hooks/useAuth';
import { PageHeader } from '@/components/shared/PageHeader';
import { ErrorBox, Modal, Spinner } from '@/components/shared/ui';
import { listItems, createItem } from '@/lib/erp';
import type { ItemCreateRequest, ItemResponse } from '@/types/api';

const NATURE_STYLES: Record<string, string> = {
  serialized: 'bg-purple-100 text-purple-700',
  bulk: 'bg-gray-100 text-gray-700',
};

const VALUATION_METHODS = ['fifo', 'moving_average', 'standard'];

export default function InventoryItemsPage() {
  const { user, isLoading: authLoading } = useAuth();
  const [items, setItems] = useState<ItemResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState<ItemCreateRequest>({
    sku: '',
    name: '',
    brand: '',
    model: '',
    category: '',
    nature: 'bulk',
    uom_code: 'unit',
    valuation_method: 'moving_average',
    default_sale_price: null,
    default_purchase_price: null,
    is_sales_item: true,
    is_purchase_item: true,
  });
  const [saving, setSaving] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const [expandedId, setExpandedId] = useState<string | null>(null);

  const fetchItems = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listItems();
      setItems(data);
    } catch (e: any) {
      setError(e?.message || 'Failed to load items.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchItems();
  }, [fetchItems]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!form.sku.trim() || !form.name.trim()) return;
    setSaving(true);
    setCreateError(null);
    try {
      const payload: ItemCreateRequest = {
        ...form,
        sku: form.sku.trim(),
        name: form.name.trim(),
        brand: form.brand?.trim() || null,
        model: form.model?.trim() || null,
        category: form.category?.trim() || null,
        uom_code: form.uom_code || 'unit',
        valuation_method: form.valuation_method || 'moving_average',
        default_purchase_price: form.default_purchase_price ?? null,
        default_sale_price: form.default_sale_price ?? null,
      };
      await createItem(payload);
      setCreateOpen(false);
      setForm({
        sku: '',
        name: '',
        brand: '',
        model: '',
        category: '',
        nature: 'bulk',
        uom_code: 'unit',
        valuation_method: 'moving_average',
        default_sale_price: null,
        default_purchase_price: null,
        is_sales_item: true,
        is_purchase_item: true,
      });
      await fetchItems();
    } catch (e: any) {
      setCreateError(e?.message || 'Failed to create item.');
    } finally {
      setSaving(false);
    }
  }

  if (authLoading || loading) return <Spinner />;
  if (error) return <ErrorBox message={error} onRetry={fetchItems} />;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Items"
        description="Item master - products, serials, pricing"
        actions={
          <button
            onClick={() => setCreateOpen(true)}
            className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground"
          >
            New Item
          </button>
        }
      />

      <div className="overflow-x-auto rounded-lg border bg-white">
        <table className="w-full text-sm">
          <thead className="border-b text-left text-xs font-medium text-muted-foreground">
            <tr>
              <th className="px-4 py-3">SKU</th>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Brand</th>
              <th className="px-4 py-3">Model</th>
              <th className="px-4 py-3">Category</th>
              <th className="px-4 py-3">Nature</th>
              <th className="px-4 py-3 text-right">Valuation</th>
              <th className="px-4 py-3 text-right">Sale Price</th>
              <th className="px-4 py-3 text-right">Purchase Price</th>
              <th className="px-4 py-3">Active</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr>
                <td colSpan={10} className="px-4 py-8 text-center text-sm text-muted-foreground">
                  No items found.
                </td>
              </tr>
            ) : (
              items.map((item) => (
                <>
                  <tr
                    key={item.id}
                    onClick={() =>
                      setExpandedId(expandedId === item.id ? null : item.id)
                    }
                    className="cursor-pointer border-b hover:bg-muted"
                  >
                    <td className="px-4 py-3 font-mono text-xs">{item.sku}</td>
                    <td className="px-4 py-3">{item.name}</td>
                    <td className="px-4 py-3">{item.brand || '—'}</td>
                    <td className="px-4 py-3">{item.model || '—'}</td>
                    <td className="px-4 py-3">{item.category || '—'}</td>
                    <td className="px-4 py-3">
                      <span
                        className={clsx(
                          'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
                          NATURE_STYLES[item.nature] || 'bg-gray-100 text-gray-700',
                        )}
                      >
                        {item.nature}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">{item.valuation_method}</td>
                    <td className="px-4 py-3 text-right">
                      {item.default_sale_price != null
                        ? `AED ${Number(item.default_sale_price).toFixed(2)}`
                        : '—'}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {item.default_purchase_price != null
                        ? `AED ${Number(item.default_purchase_price).toFixed(2)}`
                        : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={clsx(
                          'inline-block h-2.5 w-2.5 rounded-full',
                          item.is_active ? 'bg-green-500' : 'bg-gray-300',
                        )}
                        title={item.is_active ? 'Active' : 'Inactive'}
                      />
                    </td>
                  </tr>
                  {expandedId === item.id ? (
                    <tr key={`${item.id}-detail`} className="bg-muted/30">
                      <td colSpan={10} className="px-6 py-4">
                        <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm sm:grid-cols-3">
                          <Detail label="ID" value={item.id} />
                          <Detail label="Description" value={item.description || '—'} />
                          <Detail label="UOM ID" value={item.uom_id} />
                          <Detail label="Sales Item" value={item.is_sales_item ? 'Yes' : 'No'} />
                          <Detail label="Purchase Item" value={item.is_purchase_item ? 'Yes' : 'No'} />
                          <Detail label="Reorder Level" value={item.reorder_level ?? '—'} />
                          <Detail label="Reorder Qty" value={item.reorder_qty ?? '—'} />
                          <Detail label="Created" value={fmt(item.created_at)} />
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </>
              ))
            )}
          </tbody>
        </table>
      </div>

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="New Item" maxWidth="max-w-lg">
        <form onSubmit={handleCreate} className="space-y-4 text-sm">
          {createError ? <ErrorBox message={createError} /> : null}
          <div className="grid grid-cols-2 gap-4">
            <ModalField label="SKU">
              <input
                value={form.sku}
                onChange={(e) => setForm({ ...form, sku: e.target.value })}
                required
                className="rounded-md border px-3 py-1.5 text-sm w-full"
              />
            </ModalField>
            <ModalField label="Name">
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
                className="rounded-md border px-3 py-1.5 text-sm w-full"
              />
            </ModalField>
            <ModalField label="Brand">
              <input
                value={form.brand ?? ''}
                onChange={(e) => setForm({ ...form, brand: e.target.value })}
                className="rounded-md border px-3 py-1.5 text-sm w-full"
              />
            </ModalField>
            <ModalField label="Model">
              <input
                value={form.model ?? ''}
                onChange={(e) => setForm({ ...form, model: e.target.value })}
                className="rounded-md border px-3 py-1.5 text-sm w-full"
              />
            </ModalField>
            <ModalField label="Category">
              <input
                value={form.category ?? ''}
                onChange={(e) => setForm({ ...form, category: e.target.value })}
                className="rounded-md border px-3 py-1.5 text-sm w-full"
              />
            </ModalField>
            <ModalField label="Nature">
              <select
                value={form.nature}
                onChange={(e) => setForm({ ...form, nature: e.target.value })}
                className="rounded-md border px-3 py-1.5 text-sm w-full"
              >
                <option value="serialized">Serialized</option>
                <option value="bulk">Bulk</option>
              </select>
            </ModalField>
            <ModalField label="UOM Code">
              <input
                value={form.uom_code}
                onChange={(e) => setForm({ ...form, uom_code: e.target.value })}
                className="rounded-md border px-3 py-1.5 text-sm w-full"
              />
            </ModalField>
            <ModalField label="Valuation Method">
              <select
                value={form.valuation_method}
                onChange={(e) => setForm({ ...form, valuation_method: e.target.value })}
                className="rounded-md border px-3 py-1.5 text-sm w-full"
              >
                {VALUATION_METHODS.map((m) => (
                  <option key={m} value={m}>
                    {m.replace(/_/g, ' ')}
                  </option>
                ))}
              </select>
            </ModalField>
            <ModalField label="Default Sale Price">
              <input
                type="number"
                step="0.01"
                value={form.default_sale_price ?? ''}
                onChange={(e) =>
                  setForm({
                    ...form,
                    default_sale_price: e.target.value ? Number(e.target.value) : null,
                  })
                }
                className="rounded-md border px-3 py-1.5 text-sm w-full"
              />
            </ModalField>
            <ModalField label="Default Purchase Price">
              <input
                type="number"
                step="0.01"
                value={form.default_purchase_price ?? ''}
                onChange={(e) =>
                  setForm({
                    ...form,
                    default_purchase_price: e.target.value ? Number(e.target.value) : null,
                  })
                }
                className="rounded-md border px-3 py-1.5 text-sm w-full"
              />
            </ModalField>
          </div>
          <div className="flex gap-6">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.is_sales_item}
                onChange={(e) => setForm({ ...form, is_sales_item: e.target.checked })}
              />
              Sales Item
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.is_purchase_item}
                onChange={(e) => setForm({ ...form, is_purchase_item: e.target.checked })}
              />
              Purchase Item
            </label>
          </div>
          <button
            type="submit"
            disabled={saving || !form.sku.trim() || !form.name.trim()}
            className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground disabled:opacity-60"
          >
            {saving ? <Spinner className="text-primary-foreground" /> : null}
            Create Item
          </button>
        </form>
      </Modal>
    </div>
  );
}

function ModalField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-muted-foreground">{label}</label>
      {children}
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-sm">{value}</p>
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
