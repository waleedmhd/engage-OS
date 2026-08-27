'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, Search, X } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import { ErrorBox, Pagination, SkeletonRows, Spinner } from '@/components/shared/ui';
import { authedFetch } from '@/lib/authedFetch';
import { useDebounce } from '@/hooks/useDebounce';
import type {
  MarketMessageResponse,
  MarketMessageProductOut,
  ResolutionFix,
  TeachEntry,
} from '@/types/api';

const PAGE_SIZE = 25;

const SIDE_OPTIONS = ['BUY', 'SELL', 'MIXED', 'UNKNOWN'] as const;
const REVIEW_STATUS_OPTIONS = ['AUTO', 'PENDING', 'REVIEWED', 'DISMISSED'] as const;
const STATUS_OPTIONS = ['ACTIVE', 'SUPERSEDED', 'EXPIRED'] as const;

const EDITABLE_FIELDS = [
  { key: 'product_name', label: 'Product' },
  { key: 'qty', label: 'Qty' },
  { key: 'unit_price', label: 'Price' },
  { key: 'condition', label: 'Condition' },
  { key: 'grade', label: 'Grade' },
  { key: 'color', label: 'Color' },
] as const;

function detectKind(field: string): string {
  if (field === 'product_name') return 'product';
  if (field === 'color') return 'color';
  if (field === 'condition') return 'condition';
  if (field === 'grade') return 'grade';
  return 'attribute';
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
    d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// ---------------------------------------------------------------------------
// InlineEditor — click-to-edit span
// ---------------------------------------------------------------------------

function InlineEditor({
  value,
  onSave,
  numeric,
}: {
  value: string | number | null | undefined;
  onSave: (v: string) => void;
  numeric?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const display = value != null ? String(value) : '—';

  function start() {
    setDraft(value != null ? String(value) : '');
    setEditing(true);
    requestAnimationFrame(() => inputRef.current?.focus());
  }

  function commit() {
    const trimmed = draft.trim();
    if (trimmed && trimmed !== String(value ?? '')) {
      onSave(trimmed);
    }
    setEditing(false);
  }

  function cancel() {
    setEditing(false);
  }

  if (editing) {
    return (
      <input
        ref={inputRef}
        type={numeric ? 'number' : 'text'}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
          if (e.key === 'Escape') cancel();
        }}
        className="w-full rounded border px-1.5 py-0.5 text-xs outline-none focus:border-primary"
      />
    );
  }

  return (
    <button
      type="button"
      onClick={start}
      className="text-left hover:bg-accent rounded px-1 py-0.5 -mx-1 cursor-text transition-colors min-w-[2rem]"
      title={`Edit${value != null ? `: ${value}` : ''}`}
    >
      {display}
    </button>
  );
}

// ---------------------------------------------------------------------------
// TeachChips
// ---------------------------------------------------------------------------

function TeachChips({
  productId,
  edits,
  teachEntries,
  onTeachAdd,
  onTeachRemove,
}: {
  productId: string;
  edits: Record<string, string>;
  teachEntries: TeachEntry[];
  onTeachAdd: (entry: TeachEntry) => void;
  onTeachRemove: (index: number) => void;
}) {
  const [openField, setOpenField] = useState<string | null>(null);
  const [canonical, setCanonical] = useState('');

  const chips = teachEntries.filter((t) =>
    Object.keys(edits).some((f) => detectKind(f) === t.kind && edits[f] === t.alias),
  );

  function open(field: string) {
    setOpenField(field);
    setCanonical('');
  }

  function commit(field: string) {
    const alias = edits[field];
    const kind = detectKind(field);
    const canon = canonical.trim();
    if (alias && canon) {
      onTeachAdd({ kind, alias, canonical: canon });
    }
    setOpenField(null);
    setCanonical('');
  }

  if (Object.keys(edits).length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
      {Object.keys(edits).map((field) => {
        const kind = detectKind(field);
        const existing = chips.find((c) => c.kind === kind && c.alias === edits[field]);
        const isOpen = openField === field;

        if (existing) {
          return (
            <span
              key={field}
              className="inline-flex items-center gap-1 rounded-full bg-green-50 px-2 py-0.5 text-[10px] text-green-700 border border-green-200"
            >
              {existing.alias} → {existing.canonical}
              <button
                type="button"
                onClick={() => {
                  const idx = teachEntries.indexOf(existing);
                  if (idx >= 0) onTeachRemove(idx);
                }}
                className="ml-0.5 rounded-full hover:bg-green-200"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          );
        }

        if (isOpen) {
          return (
            <span
              key={field}
              className="inline-flex items-center gap-1 rounded bg-accent px-2 py-0.5 text-[10px]"
            >
              <span className="text-muted-foreground">{edits[field]}</span>
              <span>→</span>
              <input
                autoFocus
                value={canonical}
                onChange={(e) => setCanonical(e.target.value)}
                onBlur={() => commit(field)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commit(field);
                  if (e.key === 'Escape') {
                    setOpenField(null);
                    setCanonical('');
                  }
                }}
                placeholder="canonical"
                className="w-20 rounded border px-1 py-px text-[10px] outline-none focus:border-primary"
              />
            </span>
          );
        }

        return (
          <button
            key={field}
            type="button"
            onClick={() => open(field)}
            className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-[10px] text-blue-600 border border-blue-200 hover:bg-blue-100 transition-colors"
          >
            + {edits[field]} → ?
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// EditPanel — inline correction panel for a selected row
// ---------------------------------------------------------------------------

function EditPanel({
  item,
  loading,
  error,
  onSave,
  onCancel,
}: {
  item: MarketMessageResponse;
  loading: boolean;
  error: string | null;
  onSave: (correctedSide: string | null, resolutions: ResolutionFix[], teach: TeachEntry[]) => void;
  onCancel: () => void;
}) {
  const [correctedSide, setCorrectedSide] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, Record<string, string>>>({});
  const [teachEntries, setTeachEntries] = useState<TeachEntry[]>([]);

  function cycleSide() {
    const current = correctedSide ?? item.side;
    const idx = SIDE_OPTIONS.indexOf(current as typeof SIDE_OPTIONS[number]);
    const next = SIDE_OPTIONS[(idx + 1) % SIDE_OPTIONS.length];
    setCorrectedSide(next === item.side ? null : next);
  }

  function setEdit(productId: string, field: string, value: string) {
    setEdits((prev) => {
      const productEdits = { ...prev[productId] };
      productEdits[field] = value;
      return { ...prev, [productId]: productEdits };
    });
  }

  function handleTeachAdd(entry: TeachEntry) {
    setTeachEntries((prev) => [...prev, entry]);
  }

  function handleTeachRemove(index: number) {
    setTeachEntries((prev) => prev.filter((_, i) => i !== index));
  }

  const activeSide = correctedSide ?? item.side;

  return (
    <div className="rounded-lg border-2 border-primary/30 bg-white p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium">Correct Classification</h4>
        <button
          onClick={onCancel}
          className="rounded p-1 text-muted-foreground hover:bg-muted"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Message text */}
      <div className="rounded-md bg-muted p-3 text-sm whitespace-pre-wrap">
        {item.raw_text}
      </div>

      {/* Side correction */}
      <div className="flex items-center gap-3">
        <span className="text-xs text-muted-foreground">Side:</span>
        <button
          type="button"
          onClick={cycleSide}
          className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-bold uppercase cursor-pointer transition-colors ${
            activeSide === 'BUY'
              ? 'bg-blue-100 text-blue-700 hover:bg-blue-200'
              : activeSide === 'SELL'
                ? 'bg-amber-100 text-amber-700 hover:bg-amber-200'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
          }`}
          title="Click to correct side"
        >
          {activeSide}
          {correctedSide ? (
            <span className="text-[10px] font-normal lowercase">(corrected)</span>
          ) : null}
        </button>
      </div>

      {/* Product resolutions */}
      {item.products.length > 0 ? (
        <div className="space-y-3">
          <p className="text-xs font-medium text-muted-foreground">Products</p>
          {item.products.map((p) => {
            const productEdits = edits[p.id] ?? {};

            return (
              <div key={p.id} className="rounded-md border p-3 text-sm">
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-2">
                  {EDITABLE_FIELDS.map(({ key, label }) => {
                    const original = (p as any)[key] as string | number | null | undefined;
                    const edited = productEdits[key];
                    const display = edited ?? original;

                    return (
                      <div key={key} className="space-y-0.5">
                        <div className="text-[10px] text-muted-foreground uppercase tracking-wider">
                          {label}
                        </div>
                        <div className="text-xs">
                          <InlineEditor
                            value={display}
                            numeric={key === 'qty' || key === 'unit_price'}
                            onSave={(v) => setEdit(p.id, key, v)}
                          />
                        </div>
                        {edited && edited !== String(original ?? '') ? (
                          <div className="text-[9px] text-amber-600 line-through">
                            {original != null ? String(original) : '—'}
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>

                <div className="mt-2 text-[10px] text-muted-foreground">
                  via {p.resolver} · {Math.round(p.confidence * 100)}% match
                </div>

                <TeachChips
                  productId={p.id}
                  edits={productEdits}
                  teachEntries={teachEntries}
                  onTeachAdd={handleTeachAdd}
                  onTeachRemove={handleTeachRemove}
                />
              </div>
            );
          })}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No products resolved.</p>
      )}

      {/* Actions */}
      <div className="flex gap-3 pt-2 border-t">
        <button
          type="button"
          onClick={() => {
            const resolutions = item.products
              .filter((p) => edits[p.id] && Object.keys(edits[p.id]).length > 0)
              .map((p) => ({
                product_id: p.product_id,
                attributes: edits[p.id] as Record<string, unknown>,
              }));
            onSave(activeSide, resolutions, teachEntries);
          }}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
        >
          {loading ? <Spinner className="text-primary-foreground" /> : <Check className="h-4 w-4" />}
          Save Corrections
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={loading}
          className="rounded-md border px-4 py-2 text-sm font-medium text-muted-foreground hover:bg-muted disabled:opacity-40"
        >
          Cancel
        </button>

        {error ? (
          <span className="text-xs text-red-600 self-center">{error}</span>
        ) : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Review status badge
// ---------------------------------------------------------------------------

function ReviewStatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    AUTO: 'bg-green-100 text-green-700',
    PENDING: 'bg-yellow-100 text-yellow-700',
    REVIEWED: 'bg-blue-100 text-blue-700',
    DISMISSED: 'bg-gray-100 text-gray-600',
    UNREVIEWED_EXPIRED: 'bg-red-100 text-red-700',
  };
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium ${colors[status] || 'bg-gray-100 text-gray-600'}`}>
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function MarketMessagesPage() {
  const [messages, setMessages] = useState<MarketMessageResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters — raw keystroke state for input responsiveness.
  const [sideFilter, setSideFilter] = useState('');
  const [reviewFilter, setReviewFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [searchText, setSearchText] = useState('');
  const debouncedSearch = useDebounce(searchText, 300);

  // Selection / editing
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [flashId, setFlashId] = useState<string | null>(null);

  const fetchMessages = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        page_size: String(PAGE_SIZE),
        page: String(page),
      });
      if (sideFilter) params.set('side', sideFilter);
      if (reviewFilter) params.set('review_status', reviewFilter);
      if (statusFilter) params.set('status', statusFilter);
      if (debouncedSearch) params.set('q', debouncedSearch);

      const res = await authedFetch<{ items: MarketMessageResponse[]; total: number }>(
        `/market/messages?${params.toString()}`,
      );
      setMessages(res.items);
      setTotal(res.total);
    } catch {
      setError('Failed to load messages.');
    } finally {
      setLoading(false);
    }
  }, [page, sideFilter, reviewFilter, statusFilter, debouncedSearch]);

  useEffect(() => {
    fetchMessages();
  }, [fetchMessages]);

  // Reset to page 1 when debounced search changes (typing stops).
  useEffect(() => {
    setPage(1);
  }, [debouncedSearch]);

  async function handleSave(
    msg: MarketMessageResponse,
    correctedSide: string | null,
    resolutions: ResolutionFix[],
    teach: TeachEntry[],
  ) {
    setActionLoading(true);
    setActionError(null);
    try {
      await authedFetch(`/market/messages/${msg.id}/correct`, {
        method: 'POST',
        json: { corrected_side: correctedSide, resolutions, teach },
      });
      setActionLoading(false);
      setSelectedId(null);
      setFlashId(msg.id);
      setTimeout(() => setFlashId(null), 1200);
      fetchMessages();
    } catch {
      setActionLoading(false);
      setActionError('Failed to save corrections.');
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Market Messages"
        description="Browse and correct all classified market messages. Click a row to edit."
      />

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={sideFilter}
          onChange={(e) => { setSideFilter(e.target.value); setPage(1); }}
          className="rounded-md border px-3 py-2 text-sm"
        >
          <option value="">All sides</option>
          {SIDE_OPTIONS.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>

        <select
          value={reviewFilter}
          onChange={(e) => { setReviewFilter(e.target.value); setPage(1); }}
          className="rounded-md border px-3 py-2 text-sm"
        >
          <option value="">All review statuses</option>
          {REVIEW_STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>

        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
          className="rounded-md border px-3 py-2 text-sm"
        >
          <option value="">All statuses</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>

        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder="Search message text…"
            className="w-full rounded-md border py-2 pl-9 pr-3 text-sm outline-none focus:border-primary"
          />
        </div>

        <span className="text-sm text-muted-foreground tabular-nums">
          {total} message{total !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Table */}
      {loading ? (
        <SkeletonRows rows={8} />
      ) : error ? (
        <ErrorBox message={error} onRetry={fetchMessages} />
      ) : messages.length === 0 ? (
        <div className="flex min-h-[200px] items-center justify-center rounded-lg border bg-white text-sm text-muted-foreground">
          No messages found.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50 text-left text-xs text-muted-foreground">
                <th className="px-3 py-2.5 font-medium">Time</th>
                <th className="px-3 py-2.5 font-medium">Side</th>
                <th className="px-3 py-2.5 font-medium">Message</th>
                <th className="px-3 py-2.5 font-medium">Products</th>
                <th className="px-3 py-2.5 font-medium">Resolver</th>
                <th className="px-3 py-2.5 font-medium">Conf</th>
                <th className="px-3 py-2.5 font-medium">Review</th>
              </tr>
            </thead>
            <tbody>
              {messages.map((msg) => {
                const isSelected = selectedId === msg.id;
                const isFlashing = flashId === msg.id;

                return (
                  <tr key={msg.id}>
                    <td colSpan={7} className="p-0">
                      <table className="w-full">
                        <tbody>
                          <tr
                            onClick={() => setSelectedId(isSelected ? null : msg.id)}
                            className={`cursor-pointer transition-colors hover:bg-accent/50 ${
                              isSelected ? 'bg-accent' : ''
                            } ${isFlashing ? 'bg-green-50' : ''}`}
                          >
                            <td className="px-3 py-2.5 text-xs text-muted-foreground whitespace-nowrap w-[100px]">
                              {fmtTime(msg.captured_at)}
                            </td>
                            <td className="px-3 py-2.5 w-[70px]">
                              <span
                                className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${
                                  msg.side === 'BUY'
                                    ? 'bg-blue-100 text-blue-700'
                                    : msg.side === 'SELL'
                                      ? 'bg-amber-100 text-amber-700'
                                      : 'bg-gray-100 text-gray-600'
                                }`}
                              >
                                {msg.side}
                              </span>
                            </td>
                            <td className="px-3 py-2.5 max-w-[300px]">
                              <p className="truncate text-xs">{msg.raw_text}</p>
                            </td>
                            <td className="px-3 py-2.5">
                              <div className="flex flex-wrap gap-1">
                                {msg.products.length > 0 ? (
                                  msg.products.map((p: MarketMessageProductOut) => (
                                    <span
                                      key={p.id}
                                      className="inline-flex items-center rounded-full bg-accent px-2 py-0.5 text-[10px] font-medium"
                                    >
                                      {p.product_name || p.product_id.slice(0, 8)}
                                    </span>
                                  ))
                                ) : (
                                  <span className="text-[10px] text-muted-foreground">—</span>
                                )}
                              </div>
                            </td>
                            <td className="px-3 py-2.5 text-[10px] text-muted-foreground w-[70px]">
                              {msg.products[0]?.resolver || '—'}
                            </td>
                            <td className="px-3 py-2.5 text-[10px] tabular-nums w-[50px]">
                              {msg.products[0] != null
                                ? `${Math.round(msg.products[0].confidence * 100)}%`
                                : '—'}
                            </td>
                            <td className="px-3 py-2.5 w-[90px]">
                              <ReviewStatusBadge status={msg.review_status} />
                            </td>
                          </tr>

                          {/* Inline edit panel */}
                          {isSelected ? (
                            <tr>
                              <td colSpan={7} className="px-3 pb-4">
                                <EditPanel
                                  item={msg}
                                  loading={actionLoading}
                                  error={actionError}
                                  onSave={(side, resolutions, teach) =>
                                    handleSave(msg, side, resolutions, teach)
                                  }
                                  onCancel={() => setSelectedId(null)}
                                />
                              </td>
                            </tr>
                          ) : null}
                        </tbody>
                      </table>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {total > 0 ? (
        <Pagination
          page={page}
          pageSize={PAGE_SIZE}
          total={total}
          onPage={setPage}
        />
      ) : null}
    </div>
  );
}
