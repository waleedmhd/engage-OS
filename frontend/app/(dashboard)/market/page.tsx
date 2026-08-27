'use client';

import { useCallback, useEffect, useState } from 'react';
import { Search, Send, Store, ChevronDown, ChevronUp, Clock, Tag, ArrowDown, ArrowUp } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import { ErrorBox, Modal, SkeletonRows, Spinner } from '@/components/shared/ui';
import { authedFetch } from '@/lib/authedFetch';
import { fetchPage } from '@/lib/lists';
import { useDebounce } from '@/hooks/useDebounce';
import type {
  MarketSearchCard,
  MarketSearchResponse,
  ProductResponse,
  MarketMessageResponse,
  OutreachBatchRequest,
  OutreachSendResponse,
  TemplateResponse,
} from '@/types/api';

const PAGE_SIZE = 24;

function fmtAgo(minutes: number): string {
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function fmtShortTime(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
    d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function fmtPrice(price: number | null | undefined, currency?: string | null): string {
  if (price == null) return '';
  const c = currency || 'AED';
  return `${c} ${price.toLocaleString()}`;
}

function TimeBadge({ minutes, capturedAt }: { minutes: number; capturedAt: string }) {
  const urgent = minutes < 15;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${
        urgent
          ? 'bg-green-100 text-green-700'
          : 'bg-gray-100 text-gray-600'
      }`}
    >
      <Clock className="h-3 w-3" />
      {fmtAgo(minutes)}
      <span className="opacity-60">| {fmtShortTime(capturedAt)}</span>
    </span>
  );
}

export default function MarketPage() {
  const [q, setQ] = useState('');
  const debouncedQ = useDebounce(q, 300);
  const [brand, setBrand] = useState('');
  const [cursorStack, setCursorStack] = useState<(string | null)[]>([null]);
  const [pollTick, setPollTick] = useState(0);

  const [results, setResults] = useState<MarketSearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [products, setProducts] = useState<ProductResponse[]>([]);
  const [templates, setTemplates] = useState<TemplateResponse[]>([]);

  // Detail modal
  const [detail, setDetail] = useState<MarketSearchCard | null>(null);
  const [detailMsg, setDetailMsg] = useState<MarketMessageResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Outreach modal
  const [outreach, setOutreach] = useState<{
    card: MarketSearchCard;
    show: boolean;
  } | null>(null);
  const [selectedTemplate, setSelectedTemplate] = useState('');
  const [sending, setSending] = useState(false);
  const [sendResult, setSendResult] = useState<OutreachSendResponse[] | null>(null);

  // Expanded card IDs
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  // Load product catalog + templates once
  useEffect(() => {
    fetchPage<ProductResponse>('/market/products?page_size=200')
      .then((r) => setProducts(r.items))
      .catch(() => {});
    fetchPage<TemplateResponse>('/templates?page_size=100')
      .then((r) => setTemplates(r.items))
      .catch(() => {});
  }, []);

  const currentCursor = cursorStack[cursorStack.length - 1] ?? null;

  const search = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        page_size: String(PAGE_SIZE),
        q: debouncedQ,
      });
      if (brand) params.set('brand', brand);
      if (currentCursor) params.set('cursor', currentCursor);
      const res = await authedFetch<MarketSearchResponse>(
        `/market/search?${params.toString()}`,
      );
      setResults(res);
    } catch {
      setError('Search failed. Please try again.');
    } finally {
      setLoading(false);
    }
  }, [debouncedQ, brand, currentCursor]);

  useEffect(() => {
    search();
  }, [search, pollTick]);

  // Auto-refresh: reset to page 1 every 30s so newest leads appear on top
  useEffect(() => {
    const id = setInterval(() => {
      setCursorStack([null]);
      setPollTick((t) => t + 1);
    }, 30_000);
    return () => clearInterval(id);
  }, []);

  async function openDetail(card: MarketSearchCard) {
    setDetail(card);
    setDetailLoading(true);
    setDetailMsg(null);
    try {
      const msg = await authedFetch<MarketMessageResponse>(
        `/market/messages/${card.market_message_id}`,
      );
      setDetailMsg(msg);
    } catch {
      setDetailMsg(null);
    } finally {
      setDetailLoading(false);
    }
  }

  async function openOutreach(card: MarketSearchCard) {
    setOutreach({ card, show: true });
    setSelectedTemplate(templates[0]?.id ?? '');
    setSendResult(null);
  }

  async function sendOutreach() {
    if (!outreach || !selectedTemplate || !outreach.card.contact_id) return;
    setSending(true);
    try {
      const payload: OutreachBatchRequest = {
        sends: [
          {
            contact_id: outreach.card.contact_id,
            market_message_id: outreach.card.market_message_id,
            template_id: selectedTemplate,
          },
        ],
      };
      const res = await authedFetch<OutreachSendResponse[]>('/market/outreach', {
        method: 'POST',
        json: payload,
      });
      setSendResult(res);
    } catch {
      // error
    } finally {
      setSending(false);
    }
  }

  const buyCards: MarketSearchCard[] = results?.buy_items ?? [];
  const sellCards: MarketSearchCard[] = results?.sell_items ?? [];
  const buyTotal = results?.buy_total ?? 0;
  const sellTotal = results?.sell_total ?? 0;

  function goNext() {
    if (results?.next_cursor) {
      setCursorStack((prev) => [...prev, results.next_cursor!]);
    }
  }

  function goPrev() {
    setCursorStack((prev) => (prev.length > 1 ? prev.slice(0, -1) : prev));
  }

  const hasPrev = cursorStack.length > 1;
  const hasNext = results?.has_more ?? false;

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Market"
        description="WhatsApp buy/sell leads — classified, searchable, actionable."
      />

      {/* Search + filters bar */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            value={q}
            onChange={(e) => { setCursorStack([null]); setQ(e.target.value); }}
            placeholder="Search buy and sell leads…"
            className="w-full rounded-md border py-2 pl-9 pr-3 text-sm outline-none focus:border-primary"
          />
        </div>

        <select
          value={brand}
          onChange={(e) => { setCursorStack([null]); setBrand(e.target.value); }}
          className="rounded-md border px-3 py-2 text-sm"
        >
          <option value="">All brands</option>
          {products
            .map((p) => p.brand)
            .filter((v, i, a) => a.indexOf(v) === i)
            .map((b) => (
              <option key={b} value={b}>{b}</option>
            ))}
        </select>
      </div>

      {/* Resolved products */}
      {results?.resolved_products && results.resolved_products.length > 0 ? (
        <div className="flex flex-wrap gap-1.5 text-xs">
          {results.resolved_products.map((p) => (
            <span
              key={p.id}
              className="rounded-full bg-accent px-2.5 py-0.5 font-medium text-accent-foreground"
            >
              {p.canonical_name}
            </span>
          ))}
        </div>
      ) : null}

      {/* Split view: BUY | SELL */}
      {loading ? (
        <div className="space-y-2">
          <SkeletonRows rows={6} />
        </div>
      ) : error ? (
        <ErrorBox message={error} onRetry={search} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {/* BUY column */}
          <div>
            <div className="mb-3 flex items-center gap-2">
              <span className="inline-flex items-center gap-1 rounded bg-blue-100 px-2 py-0.5 text-xs font-bold uppercase text-blue-700">
                <ArrowDown className="h-3 w-3" />
                BUY ({buyTotal})
              </span>
            </div>
            {buyCards.length === 0 ? (
              <div className="flex min-h-[160px] flex-col items-center justify-center rounded-lg border border-dashed bg-white text-center">
                <Store className="mb-2 h-6 w-6 text-muted-foreground/40" />
                <p className="text-sm text-muted-foreground">
                  {q ? 'No matching buy leads.' : 'No buy leads yet.'}
                </p>
                <p className="mt-1 text-xs text-muted-foreground/60">
                  {q ? 'Try a different search term.' : 'Ingest a WhatsApp market message to populate.'}
                </p>
              </div>
            ) : (
              <div className="grid gap-3 sm:grid-cols-1 xl:grid-cols-2">
                {buyCards.map((card) => (
                  <Card
                    key={card.market_message_id}
                    card={card}
                    expanded={expanded.has(card.market_message_id)}
                    onToggleExpand={() => toggleExpand(card.market_message_id)}
                    onViewDetail={() => openDetail(card)}
                    onOutreach={() => openOutreach(card)}
                  />
                ))}
              </div>
            )}
          </div>

          {/* SELL column */}
          <div>
            <div className="mb-3 flex items-center gap-2">
              <span className="inline-flex items-center gap-1 rounded bg-amber-100 px-2 py-0.5 text-xs font-bold uppercase text-amber-700">
                <ArrowUp className="h-3 w-3" />
                SELL ({sellTotal})
              </span>
            </div>
            {sellCards.length === 0 ? (
              <div className="flex min-h-[160px] flex-col items-center justify-center rounded-lg border border-dashed bg-white text-center">
                <Tag className="mb-2 h-6 w-6 text-muted-foreground/40" />
                <p className="text-sm text-muted-foreground">
                  {q ? 'No matching sell leads.' : 'No sell leads yet.'}
                </p>
                <p className="mt-1 text-xs text-muted-foreground/60">
                  {q ? 'Try a different search term.' : 'Ingest a WhatsApp market message to populate.'}
                </p>
              </div>
            ) : (
              <div className="grid gap-3 sm:grid-cols-1 xl:grid-cols-2">
                {sellCards.map((card) => (
                  <Card
                    key={card.market_message_id}
                    card={card}
                    expanded={expanded.has(card.market_message_id)}
                    onToggleExpand={() => toggleExpand(card.market_message_id)}
                    onViewDetail={() => openDetail(card)}
                    onOutreach={() => openOutreach(card)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {!loading && !error && (hasPrev || hasNext) ? (
        <div className="flex items-center justify-center gap-4 py-4">
          <button
            onClick={() => { goPrev(); window.scrollTo(0, 0); }}
            disabled={!hasPrev}
            className="rounded-md border px-4 py-2 text-sm font-medium transition-colors hover:bg-muted disabled:opacity-30 disabled:cursor-not-allowed"
          >
            Previous
          </button>
          <span className="text-sm text-muted-foreground">
            Page {cursorStack.length}
          </span>
          <button
            onClick={() => { goNext(); window.scrollTo(0, 0); }}
            disabled={!hasNext}
            className="rounded-md border px-4 py-2 text-sm font-medium transition-colors hover:bg-muted disabled:opacity-30 disabled:cursor-not-allowed"
          >
            Next
          </button>
        </div>
      ) : null}

      {/* Detail modal */}
      <Modal
        open={Boolean(detail)}
        onClose={() => setDetail(null)}
        title={detail ? `Lead — ${detail.side}` : ''}
      >
        {detail ? (
          detailLoading ? (
            <div className="flex justify-center py-8">
              <Spinner />
            </div>
          ) : (
            <div className="space-y-4 text-sm">
              <div className="rounded-md bg-muted p-3 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">
                    {detail.sender_raw || detail.contact_name || 'Unknown sender'}
                  </span>
                  <TimeBadge minutes={detail.freshness_minutes} capturedAt={detail.captured_at} />
                </div>
                <p className="mt-2 whitespace-pre-wrap">{detail.raw_text}</p>
              </div>

              {detailMsg?.products && detailMsg.products.length > 0 ? (
                <div>
                  <h4 className="mb-2 text-xs font-medium text-muted-foreground">
                    Resolved Products
                  </h4>
                  <div className="space-y-2">
                    {detailMsg.products.map((p) => (
                      <div
                        key={p.id}
                        className="rounded-md border p-3 text-xs space-y-1"
                      >
                        <div className="font-medium">{p.product_name || p.product_id}</div>
                        <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-muted-foreground">
                          {p.qty != null ? <span>Qty: {p.qty}</span> : null}
                          {p.unit_price != null ? (
                            <span>Price: {fmtPrice(p.unit_price, p.currency)}</span>
                          ) : null}
                          {p.spec ? <span>Spec: {p.spec}</span> : null}
                          {p.condition ? <span>Condition: {p.condition}</span> : null}
                          {p.grade ? <span>Grade: {p.grade}</span> : null}
                          {p.color ? <span>Color: {p.color}</span> : null}
                        </div>
                        <span className="inline-block rounded bg-accent px-1.5 py-0.5 text-[10px] text-muted-foreground">
                          via {p.resolver} · {Math.round(p.confidence * 100)}%
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              <button
                onClick={() => {
                  setDetail(null);
                  openOutreach(detail);
                }}
                disabled={!detail.contact_id}
                className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-40"
              >
                <Send className="h-4 w-4" />
                Send Outreach
              </button>
            </div>
          )
        ) : null}
      </Modal>

      {/* Outreach modal */}
      <Modal
        open={outreach?.show ?? false}
        onClose={() => setOutreach(null)}
        title="Send Outreach"
      >
        {outreach ? (
          <div className="space-y-4 text-sm">
            {sendResult ? (
              <div className="rounded-md bg-green-50 p-4 text-sm text-green-700">
                <p className="font-medium">Outreach queued</p>
                {sendResult.map((r) => (
                  <p key={r.id} className="mt-1 text-xs text-green-600">
                    ID: {r.id} · Status: {r.status}
                  </p>
                ))}
                <button
                  onClick={() => setOutreach(null)}
                  className="mt-3 text-xs underline"
                >
                  Close
                </button>
              </div>
            ) : (
              <>
                <div className="rounded-md bg-muted p-3 text-xs">
                  <p className="font-medium">{outreach.card.contact_name || outreach.card.sender_raw || 'Unknown'}</p>
                  <p className="mt-1 text-muted-foreground line-clamp-2">
                    {outreach.card.raw_text}
                  </p>
                </div>

                <div className="space-y-1">
                  <label className="text-xs font-medium text-muted-foreground">
                    Template
                  </label>
                  <select
                    value={selectedTemplate}
                    onChange={(e) => setSelectedTemplate(e.target.value)}
                    className="w-full rounded-md border px-3 py-2 text-sm"
                  >
                    {templates.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name} ({t.category})
                      </option>
                    ))}
                  </select>
                </div>

                <button
                  onClick={sendOutreach}
                  disabled={!selectedTemplate || !outreach.card.contact_id || sending}
                  className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-40"
                >
                  {sending ? <Spinner className="text-primary-foreground" /> : null}
                  {sending ? 'Sending…' : `Send ${templates.find((t) => t.id === selectedTemplate)?.name || 'Template'}`}
                </button>
              </>
            )}
          </div>
        ) : null}
      </Modal>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Lead card component
// ---------------------------------------------------------------------------

function Card({
  card,
  expanded,
  onToggleExpand,
  onViewDetail,
  onOutreach,
}: {
  card: MarketSearchCard;
  expanded: boolean;
  onToggleExpand: () => void;
  onViewDetail: () => void;
  onOutreach: () => void;
}) {
  const primary = card.products[0];

  return (
    <div
      className="rounded-lg border bg-white transition-shadow hover:shadow-sm"
    >
      {/* Card header */}
      <div className="flex items-start justify-between px-4 pt-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${
                card.side === 'BUY'
                  ? 'bg-blue-100 text-blue-700'
                  : 'bg-amber-100 text-amber-700'
              }`}
            >
              {card.side}
            </span>
            <TimeBadge minutes={card.freshness_minutes} capturedAt={card.captured_at} />
            {(card.seen_count ?? 1) > 1 ? (
              <span
                className="inline-flex items-center gap-1 rounded-full bg-purple-100 px-2 py-0.5 text-[10px] font-medium text-purple-700 cursor-default"
                title={card.source_groups?.map(
                  (g) => g.group_name || g.source_id || 'unknown'
                ).join('\n') || ''}
              >
                ×{card.seen_count} groups
              </span>
            ) : null}
          </div>
          {primary?.product_name ? (
            <p className="mt-1.5 text-sm font-medium truncate">
              {primary.product_name}
            </p>
          ) : null}
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); onToggleExpand(); }}
          className="ml-2 rounded p-1 text-muted-foreground hover:bg-muted"
        >
          {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>
      </div>

      {/* Key data row */}
      <div className="mt-1.5 px-4">
        <p
          className={`text-xs text-muted-foreground cursor-pointer ${
            expanded ? '' : 'line-clamp-2'
          }`}
          onClick={onViewDetail}
        >
          {card.raw_text}
        </p>
      </div>

      {/* Inline extracted data */}
      {primary ? (
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 px-4 text-xs text-muted-foreground">
          {primary.qty != null ? <span>Qty: {primary.qty}</span> : null}
          {primary.unit_price != null ? (
            <span className="font-medium text-foreground">
              {fmtPrice(primary.unit_price, primary.currency)}
            </span>
          ) : null}
          {primary.spec ? <span>{primary.spec}</span> : null}
          {primary.condition ? <span>{primary.condition}</span> : null}
        </div>
      ) : null}

      {/* Expanded: all products */}
      {expanded && card.products.length > 1 ? (
        <div className="mt-2 border-t px-4 py-2 space-y-1.5">
          {card.products.map((p) => (
            <div key={p.id} className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="font-medium">{p.product_name || p.product_id}</span>
              {p.qty != null ? <span>×{p.qty}</span> : null}
              {p.unit_price != null ? <span>{fmtPrice(p.unit_price, p.currency)}</span> : null}
            </div>
          ))}
        </div>
      ) : null}

      {/* Sender info */}
      <div className="mt-2 border-t px-4 py-2 text-[11px] text-muted-foreground">
        {card.contact_name || card.sender_raw || 'Unknown'}
      </div>

      {/* Actions */}
      <div className="flex border-t">
        <button
          onClick={onViewDetail}
          className="flex-1 rounded-bl-lg py-2 text-center text-xs font-medium text-muted-foreground hover:bg-muted transition-colors"
        >
          Details
        </button>
        <button
          onClick={onOutreach}
          disabled={!card.contact_id}
          className="flex flex-1 items-center justify-center gap-1 rounded-br-lg py-2 text-xs font-medium text-primary hover:bg-accent transition-colors disabled:text-muted-foreground/30"
        >
          <Send className="h-3 w-3" />
          Outreach
        </button>
      </div>
    </div>
  );
}
