'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, X } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import { ErrorBox, Spinner, SkeletonRows } from '@/components/shared/ui';
import { EmptyState } from '@/components/shared/EmptyState';
import { authedFetch } from '@/lib/authedFetch';
import type {
  MarketReviewItem,
  ResolutionFix,
  ReviewStats,
  TeachEntry,
} from '@/types/api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtMin(n: number): string {
  if (n < 1) return '<1 min';
  if (n === 1) return '1 min';
  return `${Math.round(n)} min`;
}

const SIDE_OPTIONS = ['BUY', 'SELL', 'UNKNOWN'] as const;

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

// ---------------------------------------------------------------------------
// CapacityBar
// ---------------------------------------------------------------------------

function CapacityBar({ stats }: { stats: ReviewStats | null }) {
  if (!stats) {
    return (
      <div className="flex items-center gap-4 rounded-lg border bg-white px-4 py-3 text-sm text-muted-foreground">
        <Spinner />
        Loading stats…
      </div>
    );
  }

  const { queue_depth, inflow_7d, outflow_7d, median_review_seconds } = stats;

  const raw = stats.capacity_estimate ?? (outflow_7d > 0 ? inflow_7d / outflow_7d : inflow_7d > 0 ? 2 : 0);
  const capacity = Math.max(0, Math.min(raw, 2));

  let barColor = 'bg-green-500';
  if (capacity > 1.0) barColor = 'bg-red-500';
  else if (capacity > 0.5) barColor = 'bg-yellow-500';

  const delta = inflow_7d - outflow_7d;
  const deltaSign = delta > 0 ? '+' : '';
  const deltaColor = delta > 0 ? 'text-red-600' : delta < 0 ? 'text-green-600' : 'text-muted-foreground';

  const estMinutes = median_review_seconds
    ? (median_review_seconds * queue_depth) / 60
    : null;

  return (
    <div className="rounded-lg border bg-white px-4 py-3 space-y-2">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm">
        <span>
          <span className="text-muted-foreground">Queue: </span>
          <span className="font-semibold tabular-nums">{queue_depth}</span>
        </span>
        <span>
          <span className="text-muted-foreground">7d in: </span>
          <span className="tabular-nums">{inflow_7d}</span>
          <span className="text-muted-foreground"> / out: </span>
          <span className="tabular-nums">{outflow_7d}</span>
          <span className={`ml-1 tabular-nums ${deltaColor}`}>
            ({deltaSign}{delta})
          </span>
        </span>
        {estMinutes != null ? (
          <span className="text-muted-foreground">
            ~{fmtMin(estMinutes)} to clear
          </span>
        ) : null}
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground w-16 shrink-0">
          Capacity
        </span>
        <div className="h-2 flex-1 rounded-full bg-muted overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${barColor}`}
            style={{ width: `${Math.min(capacity * 50, 100)}%` }}
          />
        </div>
        <span className="text-xs tabular-nums text-muted-foreground w-10 text-right">
          {capacity.toFixed(1)}x
        </span>
      </div>
    </div>
  );
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
// TeachChip row
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
// ReviewCard
// ---------------------------------------------------------------------------

function ReviewCard({
  item,
  loading,
  error,
  onResolve,
  onDismiss,
  onSkip,
}: {
  item: MarketReviewItem;
  loading: boolean;
  error: string | null;
  onResolve: (correctedSide: string | null, resolutions: ResolutionFix[], teach: TeachEntry[]) => void;
  onDismiss: () => void;
  onSkip: () => void;
}) {
  const [correctedSide, setCorrectedSide] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, Record<string, string>>>({});
  const [teachEntries, setTeachEntries] = useState<TeachEntry[]>([]);
  const [flash, setFlash] = useState<'success' | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);

  // Keyboard shortcuts
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLSelectElement) {
        if (e.key === 'Escape') {
          (e.target as HTMLElement).blur();
        }
        return;
      }

      if (e.key === 'a' || e.key === 'A') {
        e.preventDefault();
        const activeSide = correctedSide ?? item.side;
        const resolutions = buildResolutions(item, edits);
        onResolve(activeSide, resolutions, teachEntries);
      } else if (e.key === 'd' || e.key === 'D') {
        e.preventDefault();
        onDismiss();
      } else if (e.key === 's' || e.key === 'S') {
        e.preventDefault();
        onSkip();
      }
    }

    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [item, correctedSide, edits, teachEntries, onResolve, onDismiss, onSkip]);

  // Flash on successful action (parent resets loading → item changes)
  const prevLoading = useRef(loading);
  useEffect(() => {
    if (prevLoading.current && !loading && !error) {
      setFlash('success');
      const t = setTimeout(() => setFlash(null), 400);
      return () => clearTimeout(t);
    }
    prevLoading.current = loading;
  }, [loading, error]);

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
    <div
      ref={containerRef}
      className={`rounded-lg border bg-white transition-colors ${
        flash === 'success' ? 'ring-2 ring-green-400' : ''
      }`}
    >
      {/* Raw message text — prominent */}
      <div className="px-5 pt-4">
        <p className="text-base leading-relaxed whitespace-pre-wrap">
          {item.raw_text}
        </p>
      </div>

      {/* Side badge + meta */}
      <div className="px-5 pt-3 flex items-center gap-3 flex-wrap">
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

        <span className="text-xs text-muted-foreground">
          {item.sender_raw || item.contact_name || 'Unknown sender'}
        </span>

        {item.review_status ? (
          <span className="rounded-full bg-yellow-100 px-2 py-0.5 text-[10px] font-medium text-yellow-700">
            {item.review_status}
          </span>
        ) : null}
      </div>

      {/* Products */}
      {item.products.length > 0 ? (
        <div className="px-5 pt-4 pb-2 space-y-3">
          {item.products.map((p) => {
            const productEdits = edits[p.id] ?? {};
            const confidences =
              item.field_confidences?.[p.id] ??
              item.field_confidences ??
              {};

            return (
              <div key={p.id} className="rounded-md border p-3 text-sm">
                {/* Editable fields grid */}
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-2">
                  {EDITABLE_FIELDS.map(({ key, label }) => {
                    const original = (p as any)[key] as string | number | null | undefined;
                    const edited = productEdits[key];
                    const display = edited ?? original;
                    const conf = confidences[key] as number | undefined;

                    return (
                      <div key={key} className="space-y-0.5">
                        <div className="text-[10px] text-muted-foreground uppercase tracking-wider">
                          {label}
                          {conf != null ? (
                            <span className="ml-1 text-[9px]">
                              {Math.round(conf * 100)}%
                            </span>
                          ) : null}
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

                {/* Resolver + confidence info */}
                <div className="mt-2 text-[10px] text-muted-foreground">
                  via {p.resolver} · {Math.round(p.confidence * 100)}% match
                </div>

                {/* Teach chips */}
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
        <div className="px-5 py-4 text-sm text-muted-foreground">
          No products resolved for this message.
        </div>
      )}

      {/* Actions row */}
      <div className="flex border-t mt-2">
        <button
          type="button"
          onClick={() => {
            const resolutions = buildResolutions(item, edits);
            onResolve(activeSide, resolutions, teachEntries);
          }}
          disabled={loading}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-bl-lg py-3 text-sm font-medium text-green-700 hover:bg-green-50 transition-colors disabled:opacity-40"
        >
          {loading ? <Spinner /> : <Check className="h-4 w-4" />}
          Approve <span className="text-[10px] text-muted-foreground">(a)</span>
        </button>
        <button
          type="button"
          onClick={onDismiss}
          disabled={loading}
          className="flex flex-1 items-center justify-center gap-1.5 py-3 text-sm font-medium text-red-600 hover:bg-red-50 transition-colors disabled:opacity-40"
        >
          <X className="h-4 w-4" />
          Dismiss <span className="text-[10px] text-muted-foreground">(d)</span>
        </button>
        <button
          type="button"
          onClick={onSkip}
          disabled={loading}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-br-lg py-3 text-sm font-medium text-muted-foreground hover:bg-muted transition-colors disabled:opacity-40"
        >
          Skip <span className="text-[10px] text-muted-foreground">(s)</span>
        </button>
      </div>

      {/* Action error */}
      {error ? (
        <div className="border-t border-red-200 bg-red-50 px-5 py-2 text-xs text-red-700">
          {error}
        </div>
      ) : null}

      {/* Keyboard hint */}
      <div className="border-t px-5 py-2 text-[10px] text-muted-foreground flex gap-4">
        <span><kbd className="rounded border px-1 py-px font-mono">a</kbd> approve</span>
        <span><kbd className="rounded border px-1 py-px font-mono">d</kbd> dismiss</span>
        <span><kbd className="rounded border px-1 py-px font-mono">s</kbd> skip</span>
        <span><kbd className="rounded border px-1 py-px font-mono">Tab</kbd> next field</span>
        <span><kbd className="rounded border px-1 py-px font-mono">Esc</kbd> cancel edit</span>
      </div>
    </div>
  );
}

function buildResolutions(
  item: MarketReviewItem,
  edits: Record<string, Record<string, string>>,
): ResolutionFix[] {
  return item.products
    .filter((p) => edits[p.id] && Object.keys(edits[p.id]).length > 0)
    .map((p) => ({
      product_id: p.product_id,
      attributes: edits[p.id] as Record<string, unknown>,
    }));
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ReviewPage() {
  const [item, setItem] = useState<MarketReviewItem | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<ReviewStats | null>(null);

  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const fetchStats = useCallback(async () => {
    try {
      const s = await authedFetch<ReviewStats>('/market/review/stats');
      setStats(s);
    } catch {
      // Stats are non-critical — silent fail
    }
  }, []);

  const fetchItem = useCallback(async (c: string | null) => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ page_size: '1' });
      if (c) params.set('cursor', c);
      const res = await authedFetch<{ items: MarketReviewItem[]; next_cursor: string | null }>(
        `/market/review?${params.toString()}`,
      );
      if (res.items.length > 0) {
        setItem(res.items[0]);
        setNextCursor(res.next_cursor);
        setCursor(c);
      } else {
        setItem(null);
        setNextCursor(null);
      }
    } catch {
      setError('Failed to load review queue. Please try again.');
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    fetchStats();
    fetchItem(null);
  }, [fetchStats, fetchItem]);

  // Stats polling
  useEffect(() => {
    const id = setInterval(fetchStats, 60_000);
    return () => clearInterval(id);
  }, [fetchStats]);

  async function handleResolve(
    correctedSide: string | null,
    resolutions: ResolutionFix[],
    teach: TeachEntry[],
  ) {
    if (!item) return;
    setActionLoading(true);
    setActionError(null);
    try {
      await authedFetch(`/market/review/${item.id}/resolve`, {
        method: 'POST',
        json: { corrected_side: correctedSide, resolutions, teach },
      });
      setActionLoading(false);
      fetchItem(null); // Re-fetch from top since queue changed
      fetchStats();
    } catch {
      setActionLoading(false);
      setActionError('Failed to approve. Please try again.');
    }
  }

  async function handleDismiss() {
    if (!item) return;
    setActionLoading(true);
    setActionError(null);
    try {
      await authedFetch(`/market/review/${item.id}/dismiss`, { method: 'POST' });
      setActionLoading(false);
      fetchItem(null); // Re-fetch from top
      fetchStats();
    } catch {
      setActionLoading(false);
      setActionError('Failed to dismiss. Please try again.');
    }
  }

  async function handleSkip() {
    fetchItem(nextCursor);
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Review Queue"
        description="Keyboard-first review: approve, correct, or dismiss parsed market messages."
      />

      <CapacityBar stats={stats} />

      {loading && !item ? (
        <div className="space-y-2">
          <SkeletonRows rows={6} />
        </div>
      ) : error && !item ? (
        <ErrorBox message={error} onRetry={() => fetchItem(null)} />
      ) : item ? (
        <ReviewCard
          key={item.id}
          item={item}
          loading={actionLoading}
          error={actionError}
          onResolve={handleResolve}
          onDismiss={handleDismiss}
          onSkip={handleSkip}
        />
      ) : (
        <EmptyState
          title="Queue clear"
          description={
            stats
              ? `${stats.queue_depth} pending · ${stats.inflow_7d} in / ${stats.outflow_7d} out last 7 days`
              : 'No pending items to review.'
          }
        />
      )}
    </div>
  );
}
