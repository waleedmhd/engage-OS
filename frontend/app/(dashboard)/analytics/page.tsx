'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  Bar,
  BarChart,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { PageHeader } from '@/components/shared/PageHeader';
import {
  ErrorBox,
  Modal,
  PermissionState,
  SkeletonRows,
  Spinner,
} from '@/components/shared/ui';
import { authedFetch } from '@/lib/authedFetch';
import { fetchPage } from '@/lib/lists';
import { useAuth } from '@/hooks/useAuth';
import type {
  AnalyticsAiResponse,
  AnalyticsConversionResponse,
  AnalyticsCostResponse,
  AnalyticsRange,
  AnalyticsRoiResponse,
  BackfillRequest,
  BackfillResponse,
  CampaignDailyPoint,
  CampaignDetailResponse,
  CampaignSummaryRow,
  ResponsivenessResponse,
  TemplateDailyPoint,
  TemplateDetailResponse,
  TemplateSummaryRow,
} from '@/types/api';

const RANGES: { label: string; value: AnalyticsRange }[] = [
  { label: '7d', value: 'week' },
  { label: '30d', value: 'month' },
  { label: '90d', value: 'quarter' },
];

const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

const HOUR_LABELS = [
  '12a', '1a', '2a', '3a', '4a', '5a', '6a', '7a', '8a', '9a', '10a', '11a',
  '12p', '1p', '2p', '3p', '4p', '5p', '6p', '7p', '8p', '9p', '10p', '11p',
];

type FetchError = Error & { status?: number };

function fmt(v: unknown): string {
  if (typeof v === 'number') return v.toFixed(2);
  if (typeof v === 'string') {
    const n = Number(v);
    return Number.isNaN(n) ? '—' : n.toFixed(2);
  }
  return '—';
}

// ---- Recharts defaults ---------------------------------------------------

const CHART_COLORS = [
  '#2563eb', '#7c3aed', '#db2777', '#ea580c', '#16a34a', '#0891b2',
  '#4f46e5', '#be123c', '#ca8a04', '#059669',
];

// ---------------------------------------------------------------------------

export default function AnalyticsPage() {
  const { user, isLoading: authLoading } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [range, setRange] = useState<AnalyticsRange>('month');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);

  const [cost, setCost] = useState<AnalyticsCostResponse | null>(null);
  const [conv, setConv] = useState<AnalyticsConversionResponse | null>(null);
  const [ai, setAi] = useState<AnalyticsAiResponse | null>(null);
  const [roi, setRoi] = useState<AnalyticsRoiResponse | null>(null);
  const [rows, setRows] = useState<CampaignSummaryRow[]>([]);
  const [templates, setTemplates] = useState<TemplateSummaryRow[]>([]);
  const [resp, setResp] = useState<ResponsivenessResponse | null>(null);

  // Campaign detail modal
  const [detail, setDetail] = useState<CampaignDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // Template detail modal
  const [tplDetail, setTplDetail] = useState<TemplateDetailResponse | null>(null);
  const [tplDetailLoading, setTplDetailLoading] = useState(false);
  const [tplDetailError, setTplDetailError] = useState<string | null>(null);

  // Backfill
  const [backfillDays, setBackfillDays] = useState('');
  const [backfillResult, setBackfillResult] = useState<string | null>(null);
  const [backfillRunning, setBackfillRunning] = useState(false);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    setForbidden(false);
    try {
      const qs = `?range=${range}`;
      const [c, cv, a, r, camp, tpl, rsp] = await Promise.all([
        authedFetch<AnalyticsCostResponse>(`/analytics/cost${qs}`),
        authedFetch<AnalyticsConversionResponse>(`/analytics/conversion${qs}`),
        authedFetch<AnalyticsAiResponse>(`/analytics/ai${qs}`),
        authedFetch<AnalyticsRoiResponse>(`/analytics/roi${qs}`),
        fetchPage<CampaignSummaryRow>(
          `/analytics/campaigns${qs}&page=1&page_size=50`,
        ),
        fetchPage<TemplateSummaryRow>(
          `/analytics/templates${qs}&page=1&page_size=50`,
        ),
        authedFetch<ResponsivenessResponse>(`/analytics/responsiveness${qs}`),
      ]);
      setCost(c);
      setConv(cv);
      setAi(a);
      setRoi(r);
      setRows(camp.items);
      setTemplates(tpl.items);
      setResp(rsp);
    } catch (err) {
      if ((err as FetchError).status === 403) {
        setForbidden(true);
      } else {
        setError('Failed to load analytics.');
      }
    } finally {
      setLoading(false);
    }
  }, [range]);

  useEffect(() => {
    if (isAdmin) fetchAll();
  }, [isAdmin, fetchAll]);

  const openDetail = useCallback(
    async (campaignId: string) => {
      setDetailLoading(true);
      setDetailError(null);
      try {
        const d = await authedFetch<CampaignDetailResponse>(
          `/analytics/campaigns/${campaignId}?range=${range}`,
        );
        setDetail(d);
      } catch {
        setDetailError('Failed to load campaign detail.');
      } finally {
        setDetailLoading(false);
      }
    },
    [range],
  );

  const openTemplateDetail = useCallback(
    async (templateId: string) => {
      setTplDetailLoading(true);
      setTplDetailError(null);
      try {
        const d = await authedFetch<TemplateDetailResponse>(
          `/analytics/templates/${templateId}?range=${range}`,
        );
        setTplDetail(d);
      } catch {
        setTplDetailError('Failed to load template detail.');
      } finally {
        setTplDetailLoading(false);
      }
    },
    [range],
  );

  const triggerBackfill = useCallback(async () => {
    const days = parseInt(backfillDays, 10);
    if (Number.isNaN(days) || days < 1 || days > 365) return;
    setBackfillRunning(true);
    setBackfillResult(null);
    try {
      const today = new Date();
      const end = today.toISOString().slice(0, 10);
      const start = new Date(today.getTime() - days * 86400000)
        .toISOString()
        .slice(0, 10);
      const body: BackfillRequest = { start_date: start, end_date: end };
      const res = await authedFetch<BackfillResponse>('/analytics/backfill', {
        method: 'POST',
        json: body,
      });
      setBackfillResult(
        `Backfill queued — task ${res.task_id} (${res.start_date} → ${res.end_date})`,
      );
    } catch {
      setBackfillResult('Backfill request failed.');
    } finally {
      setBackfillRunning(false);
    }
  }, [backfillDays]);

  if (authLoading) {
    return (
      <div className="space-y-6">
        <PageHeader title="Analytics" description="Cost, conversion, AI handling, and revenue metrics." />
        <SkeletonRows rows={4} />
      </div>
    );
  }

  if (!isAdmin || forbidden) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Analytics"
          description="Cost, conversion, AI handling, and revenue metrics."
        />
        <PermissionState title="Analytics is admin-only" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Analytics"
        description="Cost, conversion, AI handling, and revenue metrics."
        actions={
          <div className="flex items-center gap-3">
            <div className="flex gap-1 rounded-md border p-1">
              {RANGES.map((r) => (
                <button
                  key={r.value}
                  onClick={() => setRange(r.value)}
                  className={`rounded px-3 py-1 text-sm font-medium ${
                    range === r.value ? 'bg-primary text-primary-foreground' : ''
                  }`}
                >
                  {r.label}
                </button>
              ))}
            </div>

            {/* Backfill trigger */}
            <div className="flex items-center gap-1">
              <input
                type="number"
                min={1}
                max={365}
                placeholder="Days"
                value={backfillDays}
                onChange={(e) => setBackfillDays(e.target.value)}
                className="w-16 rounded-md border px-2 py-1 text-sm"
              />
              <button
                onClick={triggerBackfill}
                disabled={backfillRunning}
                className="rounded-md border px-2 py-1 text-xs font-medium hover:bg-muted disabled:opacity-50"
              >
                {backfillRunning ? <Spinner className="h-3 w-3" /> : 'Backfill'}
              </button>
            </div>
          </div>
        }
      />

      {backfillResult ? (
        <div className="rounded-md border bg-blue-50 px-4 py-3 text-sm text-blue-700">
          {backfillResult}
        </div>
      ) : null}

      {loading ? (
        <SkeletonRows rows={4} />
      ) : error ? (
        <ErrorBox message={error} onRetry={fetchAll} />
      ) : (
        <>
          {/* ---- Summary cards ---- */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <Card
              label="Total Cost"
              value={`$${fmt(cost?.total_cost_usd)}`}
            />
            <Card
              label="WhatsApp Cost (AED)"
              value={`AED ${fmt(cost?.meta_cost_aed)}`}
            />
            <Card
              label="Response Rate"
              value={
                conv ? `${(conv.response_rate * 100).toFixed(1)}%` : '—'
              }
            />
            <Card
              label="AI Tokens"
              value={
                cost ? `${((cost.tokens_input ?? 0) + (cost.tokens_output ?? 0)).toLocaleString()}` : '—'
              }
              subtitle={cost ? `in: ${(cost.tokens_input ?? 0).toLocaleString()} · out: ${(cost.tokens_output ?? 0).toLocaleString()}` : undefined}
            />
            <Card
              label="Overall ROI"
              value={
                roi?.overall_roi != null
                  ? `${(roi.overall_roi * 100).toFixed(1)}%`
                  : '—'
              }
            />
          </div>

          {/* ---- Campaign table ---- */}
          <Section title="Campaign Performance">
            <div className="overflow-x-auto rounded-lg border bg-white">
              <table className="w-full min-w-[800px] text-left text-sm">
                <thead className="border-b text-xs text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3">Campaign</th>
                    <th className="px-4 py-3">Template</th>
                    <th className="px-4 py-3">Sent</th>
                    <th className="px-4 py-3">Delivered</th>
                    <th className="px-4 py-3">Responded</th>
                    <th className="px-4 py-3">Rate</th>
                    <th className="px-4 py-3">Revenue</th>
                    <th className="px-4 py-3">Cost</th>
                    <th className="px-4 py-3">Meta AED</th>
                    <th className="px-4 py-3">ROI</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.length === 0 ? (
                    <tr>
                      <td
                        colSpan={10}
                        className="px-4 py-6 text-center text-muted-foreground"
                      >
                        No campaign data for this range.
                      </td>
                    </tr>
                  ) : (
                    rows.map((row) => (
                      <tr
                        key={row.campaign_id}
                        className="cursor-pointer border-b hover:bg-muted/50"
                        onClick={() => openDetail(row.campaign_id)}
                      >
                        <td className="px-4 py-3 font-medium">
                          {row.campaign_name}
                        </td>
                        <td className="px-4 py-3 text-xs text-muted-foreground">
                          {row.template_name || '—'}
                        </td>
                        <td className="px-4 py-3">{row.recipients_sent}</td>
                        <td className="px-4 py-3">{row.recipients_delivered}</td>
                        <td className="px-4 py-3">{row.recipients_responded}</td>
                        <td className="px-4 py-3">
                          {(row.response_rate * 100).toFixed(1)}%
                        </td>
                        <td className="px-4 py-3">
                          ${fmt(row.revenue_usd)}
                        </td>
                        <td className="px-4 py-3">${fmt(row.cost_usd)}</td>
                        <td className="px-4 py-3">
                          AED {fmt(row.meta_cost_aed)}
                        </td>
                        <td className="px-4 py-3">
                          {row.roi != null
                            ? `${(row.roi * 100).toFixed(1)}%`
                            : '—'}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </Section>

          {/* ---- Template Performance ---- */}
          <Section title="Template Performance">
            {templates.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No template data for this range.
              </p>
            ) : (
              <div className="grid gap-6 lg:grid-cols-2">
                {/* Template response rate bar chart */}
                <div className="rounded-lg border bg-white p-4">
                  <h3 className="mb-3 text-xs font-semibold text-muted-foreground">
                    Response Rate by Template
                  </h3>
                  <ResponsiveContainer width="100%" height={280}>
                    <BarChart
                      data={templates.map((t) => ({
                        name: t.template_name,
                        rate: +(t.response_rate * 100).toFixed(1),
                      }))}
                      margin={{ top: 4, right: 16, left: 0, bottom: 4 }}
                    >
                      <XAxis
                        dataKey="name"
                        tick={{ fontSize: 11 }}
                        angle={-20}
                        textAnchor="end"
                        height={60}
                      />
                      <YAxis
                        unit="%"
                        tick={{ fontSize: 11 }}
                        width={45}
                      />
                      <Tooltip formatter={(v: number) => `${v}%`} />
                      <Bar dataKey="rate" name="Response Rate" radius={[4, 4, 0, 0]}>
                        {templates.map((_, i) => (
                          <Cell
                            key={i}
                            fill={CHART_COLORS[i % CHART_COLORS.length]}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>

                {/* Template send volume bar chart */}
                <div className="rounded-lg border bg-white p-4">
                  <h3 className="mb-3 text-xs font-semibold text-muted-foreground">
                    Send Volume by Template
                  </h3>
                  <ResponsiveContainer width="100%" height={280}>
                    <BarChart
                      data={templates.map((t) => ({
                        name: t.template_name,
                        sent: t.recipients_sent,
                        responded: t.recipients_responded,
                      }))}
                      margin={{ top: 4, right: 16, left: 0, bottom: 4 }}
                    >
                      <XAxis
                        dataKey="name"
                        tick={{ fontSize: 11 }}
                        angle={-20}
                        textAnchor="end"
                        height={60}
                      />
                      <YAxis tick={{ fontSize: 11 }} width={45} />
                      <Tooltip />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <Bar
                        dataKey="sent"
                        name="Sent"
                        fill={CHART_COLORS[0]}
                        radius={[4, 4, 0, 0]}
                      />
                      <Bar
                        dataKey="responded"
                        name="Responded"
                        fill={CHART_COLORS[2]}
                        radius={[4, 4, 0, 0]}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}

            {/* Template table */}
            {templates.length > 0 && (
              <div className="overflow-x-auto rounded-lg border bg-white">
                <table className="w-full min-w-[720px] text-left text-sm">
                  <thead className="border-b text-xs text-muted-foreground">
                    <tr>
                      <th className="px-4 py-3">Template</th>
                      <th className="px-4 py-3">Campaigns</th>
                      <th className="px-4 py-3">Sent</th>
                      <th className="px-4 py-3">Delivered</th>
                      <th className="px-4 py-3">Responded</th>
                      <th className="px-4 py-3">Rate</th>
                      <th className="px-4 py-3">Meta AED</th>
                      <th className="px-4 py-3">Cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {templates.map((t) => (
                      <tr
                        key={t.template_id}
                        className="cursor-pointer border-b hover:bg-muted/50"
                        onClick={() => openTemplateDetail(t.template_id)}
                      >
                        <td className="px-4 py-3 font-medium">
                          {t.template_name}
                        </td>
                        <td className="px-4 py-3">{t.campaigns_used}</td>
                        <td className="px-4 py-3">{t.recipients_sent}</td>
                        <td className="px-4 py-3">{t.recipients_delivered}</td>
                        <td className="px-4 py-3">{t.recipients_responded}</td>
                        <td className="px-4 py-3">
                          {(t.response_rate * 100).toFixed(1)}%
                        </td>
                        <td className="px-4 py-3">
                          AED {fmt(t.meta_cost_aed)}
                        </td>
                        <td className="px-4 py-3">${fmt(t.total_cost_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>

          {/* ---- Responsiveness ---- */}
          {resp && (
            <Section title="When People Respond">
              <div className="grid gap-6 lg:grid-cols-2">
                {/* Day-of-week pie chart */}
                <div className="rounded-lg border bg-white p-4">
                  <h3 className="mb-3 text-xs font-semibold text-muted-foreground">
                    Responses by Day of Week
                  </h3>
                  <ResponsiveContainer width="100%" height={300}>
                    <PieChart>
                      <Pie
                        data={resp.by_day_of_week.map((d) => ({
                          name: DAY_LABELS[d.day_of_week] ?? String(d.day_of_week),
                          value: d.messages_received,
                        }))}
                        cx="50%"
                        cy="50%"
                        outerRadius={100}
                        dataKey="value"
                        label={({ name, percent }) =>
                          `${name} ${(percent * 100).toFixed(0)}%`
                        }
                      >
                        {resp.by_day_of_week.map((_, i) => (
                          <Cell
                            key={i}
                            fill={CHART_COLORS[i % CHART_COLORS.length]}
                          />
                        ))}
                      </Pie>
                      <Tooltip formatter={(v: number) => [v, 'Responses']} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>

                {/* Day-of-week response rate bar chart */}
                <div className="rounded-lg border bg-white p-4">
                  <h3 className="mb-3 text-xs font-semibold text-muted-foreground">
                    Response Rate by Day of Week
                  </h3>
                  <ResponsiveContainer width="100%" height={300}>
                    <BarChart
                      data={resp.by_day_of_week.map((d) => ({
                        name: DAY_LABELS[d.day_of_week] ?? String(d.day_of_week),
                        rate: +(d.response_rate * 100).toFixed(1),
                        received: d.messages_received,
                      }))}
                      margin={{ top: 4, right: 16, left: 0, bottom: 4 }}
                    >
                      <XAxis
                        dataKey="name"
                        tick={{ fontSize: 12 }}
                      />
                      <YAxis unit="%" tick={{ fontSize: 11 }} width={45} />
                      <Tooltip
                        formatter={(v: number, _name: string) => [
                          _name === 'rate' ? `${v}%` : v,
                          _name === 'rate' ? 'Response Rate' : 'Responses',
                        ]}
                      />
                      <Bar
                        dataKey="rate"
                        name="Response Rate"
                        radius={[4, 4, 0, 0]}
                      >
                        {resp.by_day_of_week.map((_, i) => (
                          <Cell
                            key={i}
                            fill={CHART_COLORS[i % CHART_COLORS.length]}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>

                {/* Time-of-day bar chart */}
                <div className="rounded-lg border bg-white p-4 lg:col-span-2">
                  <h3 className="mb-3 text-xs font-semibold text-muted-foreground">
                    Response Rate by Hour of Day (UTC)
                  </h3>
                  <ResponsiveContainer width="100%" height={300}>
                    <BarChart
                      data={resp.by_hour.map((h) => ({
                        name: HOUR_LABELS[h.hour] ?? `${h.hour}`,
                        rate: +(h.response_rate * 100).toFixed(1),
                        sent: h.messages_sent,
                        received: h.messages_received,
                      }))}
                      margin={{ top: 4, right: 16, left: 0, bottom: 4 }}
                    >
                      <XAxis
                        dataKey="name"
                        tick={{ fontSize: 10 }}
                        interval={1}
                      />
                      <YAxis unit="%" tick={{ fontSize: 11 }} width={45} />
                      <Tooltip
                        formatter={(v: number, _name: string) => [
                          _name === 'rate' ? `${v}%` : v,
                          _name === 'rate'
                            ? 'Response Rate'
                            : _name === 'sent'
                              ? 'Sent'
                              : 'Received',
                        ]}
                      />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <Bar
                        dataKey="rate"
                        name="Response Rate"
                        fill={CHART_COLORS[0]}
                        radius={[4, 4, 0, 0]}
                      />
                      <Bar
                        dataKey="sent"
                        name="Sent"
                        fill={CHART_COLORS[1]}
                        radius={[4, 4, 0, 0]}
                      />
                      <Bar
                        dataKey="received"
                        name="Received"
                        fill={CHART_COLORS[2]}
                        radius={[4, 4, 0, 0]}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </Section>
          )}
        </>
      )}

      {/* Campaign detail modal */}
      <Modal
        open={detail !== null || detailLoading || detailError !== null}
        onClose={() => {
          setDetail(null);
          setDetailError(null);
        }}
        title={detail?.campaign_name ?? 'Campaign Detail'}
      >
        {detailLoading ? (
          <div className="flex items-center justify-center py-12">
            <Spinner className="h-5 w-5" />
          </div>
        ) : detailError ? (
          <ErrorBox message={detailError} />
        ) : detail ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Stat label="Sent" value={detail.totals.recipients_sent} />
              <Stat label="Delivered" value={detail.totals.recipients_delivered} />
              <Stat label="Responded" value={detail.totals.recipients_responded} />
              <Stat
                label="Response Rate"
                value={`${(detail.totals.response_rate * 100).toFixed(1)}%`}
              />
              <Stat label="Revenue" value={`$${fmt(detail.totals.revenue_usd)}`} />
              <Stat label="Cost" value={`$${fmt(detail.totals.cost_usd)}`} />
              <Stat label="Meta Cost (AED)" value={`AED ${fmt(detail.totals.meta_cost_aed)}`} />
              <Stat label="AI Tokens" value={`${(detail.totals.tokens_input ?? 0).toLocaleString()} in · ${(detail.totals.tokens_output ?? 0).toLocaleString()} out`} />
              <Stat
                label="ROI"
                value={
                  detail.totals.roi != null
                    ? `${(detail.totals.roi * 100).toFixed(1)}%`
                    : '—'
                }
              />
            </div>

            {detail.by_day.length > 0 ? (
              <div>
                <h3 className="mb-2 text-xs font-semibold text-muted-foreground">
                  Daily Breakdown
                </h3>
                <div className="max-h-64 space-y-1 overflow-y-auto">
                  {detail.by_day.map((d: CampaignDailyPoint) => (
                    <div
                      key={d.metric_date}
                      className="flex items-center justify-between rounded-md border px-3 py-2 text-xs"
                    >
                      <span className="font-medium">{d.metric_date}</span>
                      <span>
                        {d.recipients_sent} sent · {d.recipients_delivered} del ·{' '}
                        {d.recipients_responded} resp
                      </span>
                      <span className="text-muted-foreground">
                        ${fmt(d.revenue_usd)} rev · ${fmt(d.cost_usd)} cost
                        {d.roi != null ? ` · ${(d.roi * 100).toFixed(1)}% ROI` : ''}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No daily data for this range.</p>
            )}
          </div>
        ) : null}
      </Modal>

      {/* Template detail modal */}
      <Modal
        open={tplDetail !== null || tplDetailLoading || tplDetailError !== null}
        onClose={() => {
          setTplDetail(null);
          setTplDetailError(null);
        }}
        title={tplDetail?.template_name ?? 'Template Detail'}
      >
        {tplDetailLoading ? (
          <div className="flex items-center justify-center py-12">
            <Spinner className="h-5 w-5" />
          </div>
        ) : tplDetailError ? (
          <ErrorBox message={tplDetailError} />
        ) : tplDetail ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Stat label="Campaigns Used" value={tplDetail.totals.campaigns_used} />
              <Stat label="Sent" value={tplDetail.totals.recipients_sent} />
              <Stat label="Delivered" value={tplDetail.totals.recipients_delivered} />
              <Stat label="Responded" value={tplDetail.totals.recipients_responded} />
              <Stat
                label="Response Rate"
                value={`${(tplDetail.totals.response_rate * 100).toFixed(1)}%`}
              />
              <Stat label="Meta Cost (AED)" value={`AED ${fmt(tplDetail.totals.meta_cost_aed)}`} />
              <Stat label="AI Tokens" value={`${(tplDetail.totals.tokens_input ?? 0).toLocaleString()} in · ${(tplDetail.totals.tokens_output ?? 0).toLocaleString()} out`} />
              <Stat label="Cost" value={`$${fmt(tplDetail.totals.total_cost_usd)}`} />
            </div>

            {tplDetail.by_day.length > 0 ? (
              <div>
                <h3 className="mb-2 text-xs font-semibold text-muted-foreground">
                  Daily Breakdown
                </h3>
                <div className="max-h-64 space-y-1 overflow-y-auto">
                  {tplDetail.by_day.map((d: TemplateDailyPoint) => (
                    <div
                      key={d.metric_date}
                      className="flex items-center justify-between rounded-md border px-3 py-2 text-xs"
                    >
                      <span className="font-medium">{d.metric_date}</span>
                      <span>
                        {d.recipients_sent} sent · {d.recipients_delivered} del ·{' '}
                        {d.recipients_responded} resp
                      </span>
                      <span className="text-muted-foreground">
                        {d.campaigns_used} campaigns · ${fmt(d.total_cost_usd)} cost
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No daily data for this range.</p>
            )}
          </div>
        ) : null}
      </Modal>
    </div>
  );
}

function Card({ label, value, subtitle }: { label: string; value: string; subtitle?: string }) {
  return (
    <div className="rounded-lg border bg-white p-5">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="mt-2 text-2xl font-semibold">{value}</p>
      {subtitle ? (
        <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>
      ) : null}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm font-medium">{value}</p>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-3">
      <h2 className="text-base font-semibold">{title}</h2>
      {children}
    </div>
  );
}
