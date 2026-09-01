'use client';

import { useCallback, useEffect, useState } from 'react';
import clsx from 'clsx';
import { useAuth } from '@/hooks/useAuth';
import { PageHeader } from '@/components/shared/PageHeader';
import { ErrorBox, Spinner } from '@/components/shared/ui';
import { getTrialBalance, getPLReport, getBalanceSheet } from '@/lib/erp';
import type { BalanceSheetResponse, PLReportResponse, TrialBalanceResponse } from '@/types/api';

type TabKey = 'trial-balance' | 'pl' | 'balance-sheet';

export default function ReportsPage() {
  const { user, isLoading: authLoading } = useAuth();
  const [tab, setTab] = useState<TabKey>('trial-balance');

  // Trial Balance
  const [tbDate, setTbDate] = useState(new Date().toISOString().slice(0, 10));
  const [tbData, setTbData] = useState<TrialBalanceResponse | null>(null);
  const [tbLoading, setTbLoading] = useState(false);
  const [tbError, setTbError] = useState<string | null>(null);

  // P&L
  const [plYear, setPlYear] = useState(new Date().getFullYear());
  const [plData, setPlData] = useState<PLReportResponse | null>(null);
  const [plLoading, setPlLoading] = useState(false);
  const [plError, setPlError] = useState<string | null>(null);

  // Balance Sheet
  const [bsDate, setBsDate] = useState(new Date().toISOString().slice(0, 10));
  const [bsData, setBsData] = useState<BalanceSheetResponse | null>(null);
  const [bsLoading, setBsLoading] = useState(false);
  const [bsError, setBsError] = useState<string | null>(null);

  // Fetch on tab/mount
  const fetchTrialBalance = useCallback(async () => {
    setTbLoading(true);
    setTbError(null);
    try {
      const data = await getTrialBalance(tbDate);
      setTbData(data);
    } catch (e: any) {
      setTbError(e?.message || 'Failed to load trial balance.');
    } finally {
      setTbLoading(false);
    }
  }, [tbDate]);

  const fetchPL = useCallback(async () => {
    setPlLoading(true);
    setPlError(null);
    try {
      const data = await getPLReport(plYear);
      setPlData(data);
    } catch (e: any) {
      setPlError(e?.message || 'Failed to load P&L.');
    } finally {
      setPlLoading(false);
    }
  }, [plYear]);

  const fetchBS = useCallback(async () => {
    setBsLoading(true);
    setBsError(null);
    try {
      const data = await getBalanceSheet(bsDate);
      setBsData(data);
    } catch (e: any) {
      setBsError(e?.message || 'Failed to load balance sheet.');
    } finally {
      setBsLoading(false);
    }
  }, [bsDate]);

  useEffect(() => {
    if (tab === 'trial-balance') fetchTrialBalance();
    else if (tab === 'pl') fetchPL();
    else if (tab === 'balance-sheet') fetchBS();
  }, [tab, fetchTrialBalance, fetchPL, fetchBS]);

  if (authLoading) return <Spinner />;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Reports"
        description="Financial statements and inventory reports"
      />

      {/* Tabs */}
      <div className="flex gap-1 border-b pb-0">
        {(['trial-balance', 'pl', 'balance-sheet'] as TabKey[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={clsx(
              'px-4 py-2 text-sm font-medium',
              tab === t
                ? 'border-b-2 border-primary text-primary'
                : 'text-muted-foreground',
            )}
          >
            {t === 'trial-balance'
              ? 'Trial Balance'
              : t === 'pl'
                ? 'Profit & Loss'
                : 'Balance Sheet'}
          </button>
        ))}
      </div>

      {/* Trial Balance */}
      {tab === 'trial-balance' ? (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <label className="text-sm text-muted-foreground">As of Date:</label>
            <input
              type="date"
              value={tbDate}
              onChange={(e) => setTbDate(e.target.value)}
              className="rounded-md border px-3 py-1.5 text-sm"
            />
            <button
              onClick={fetchTrialBalance}
              className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground"
            >
              Refresh
            </button>
          </div>

          {tbError ? <ErrorBox message={tbError} onRetry={fetchTrialBalance} /> : null}

          {tbLoading ? (
            <Spinner />
          ) : tbData ? (
            <div className="overflow-x-auto rounded-lg border bg-white">
              <table className="w-full text-sm">
                <thead className="border-b text-left text-xs font-medium text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3">Code</th>
                    <th className="px-4 py-3">Name</th>
                    <th className="px-4 py-3 text-right">Opening DR</th>
                    <th className="px-4 py-3 text-right">Opening CR</th>
                    <th className="px-4 py-3 text-right">Period DR</th>
                    <th className="px-4 py-3 text-right">Period CR</th>
                    <th className="px-4 py-3 text-right">Closing DR</th>
                    <th className="px-4 py-3 text-right">Closing CR</th>
                  </tr>
                </thead>
                <tbody>
                  {tbData.rows.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="px-4 py-8 text-center text-muted-foreground">
                        No data.
                      </td>
                    </tr>
                  ) : (
                    <>
                      {tbData.rows.map((row, i) => (
                        <tr key={i} className="border-b">
                          <td className="px-4 py-2 font-mono text-xs">{row.account_code}</td>
                          <td className="px-4 py-2">{row.account_name}</td>
                          <td className="px-4 py-2 text-right">
                            {row.opening_dr ? Number(row.opening_dr).toFixed(2) : '—'}
                          </td>
                          <td className="px-4 py-2 text-right">
                            {row.opening_cr ? Number(row.opening_cr).toFixed(2) : '—'}
                          </td>
                          <td className="px-4 py-2 text-right">
                            {row.period_dr ? Number(row.period_dr).toFixed(2) : '—'}
                          </td>
                          <td className="px-4 py-2 text-right">
                            {row.period_cr ? Number(row.period_cr).toFixed(2) : '—'}
                          </td>
                          <td className="px-4 py-2 text-right">
                            {row.closing_dr ? Number(row.closing_dr).toFixed(2) : '—'}
                          </td>
                          <td className="px-4 py-2 text-right">
                            {row.closing_cr ? Number(row.closing_cr).toFixed(2) : '—'}
                          </td>
                        </tr>
                      ))}
                      {/* Totals footer */}
                      <tr className="border-t-2 bg-muted/30 font-medium">
                        <td className="px-4 py-2" colSpan={2}>Totals</td>
                        <td className="px-4 py-2 text-right">
                          {Number(tbData.total_dr).toFixed(2)}
                        </td>
                        <td className="px-4 py-2 text-right">
                          {Number(tbData.total_cr).toFixed(2)}
                        </td>
                        <td colSpan={4} />
                      </tr>
                      <tr className="bg-muted/20">
                        <td className="px-4 py-2" colSpan={2}>Difference</td>
                        <td
                          colSpan={2}
                          className={clsx(
                            'px-4 py-2 text-right font-bold',
                            Number(tbData.difference) === 0
                              ? 'text-green-600'
                              : 'text-red-600',
                          )}
                        >
                          {Number(tbData.difference).toFixed(2)}
                          {Number(tbData.difference) === 0 ? ' (Balanced)' : ' (Out of balance)'}
                        </td>
                        <td colSpan={4} />
                      </tr>
                    </>
                  )}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ) : null}

      {/* Profit & Loss */}
      {tab === 'pl' ? (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <label className="text-sm text-muted-foreground">Fiscal Year:</label>
            <input
              type="number"
              value={plYear}
              onChange={(e) => setPlYear(Number(e.target.value))}
              className="rounded-md border px-3 py-1.5 text-sm w-24"
            />
            <button
              onClick={fetchPL}
              className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground"
            >
              Refresh
            </button>
          </div>

          {plError ? <ErrorBox message={plError} onRetry={fetchPL} /> : null}

          {plLoading ? (
            <Spinner />
          ) : plData ? (
            <div className="space-y-4">
              {/* Summary cards */}
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
                <StatCard label="Revenue" value={plData.revenue} color="text-green-600" />
                <StatCard label="COGS" value={plData.cogs} color="text-red-600" />
                <StatCard label="Gross Profit" value={plData.gross_profit} color="text-blue-600" />
                <StatCard label="OPEX" value={plData.opex} color="text-red-600" />
                <StatCard
                  label="Net Profit"
                  value={plData.net_profit}
                  color={plData.net_profit >= 0 ? 'text-green-600' : 'text-red-600'}
                />
              </div>

              {/* Account breakdown */}
              {plData.accounts && plData.accounts.length > 0 ? (
                <div className="overflow-x-auto rounded-lg border bg-white">
                  <table className="w-full text-sm">
                    <thead className="border-b text-left text-xs font-medium text-muted-foreground">
                      <tr>
                        <th className="px-4 py-3">Code</th>
                        <th className="px-4 py-3">Name</th>
                        <th className="px-4 py-3 text-right">Balance</th>
                      </tr>
                    </thead>
                    <tbody>
                      {plData.accounts.map((a, i) => (
                        <tr key={i} className="border-b">
                          <td className="px-4 py-2 font-mono text-xs">{a.code}</td>
                          <td className="px-4 py-2">{a.name}</td>
                          <td className="px-4 py-2 text-right">
                            AED {Number(a.balance).toFixed(2)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}

              <div className="rounded-lg border bg-white p-6">
                <p className="text-xs text-muted-foreground">
                  Revenue - COGS = Gross Profit - OPEX = Net Profit
                </p>
                <div className="mt-2 space-y-1 text-sm font-mono">
                  <p>
                    {Number(plData.revenue).toFixed(2)} - {Number(plData.cogs).toFixed(2)} ={' '}
                    <span className="font-semibold">{Number(plData.gross_profit).toFixed(2)}</span>
                  </p>
                  <p>
                    {Number(plData.gross_profit).toFixed(2)} - {Number(plData.opex).toFixed(2)} ={' '}
                    <span className="font-semibold">{Number(plData.net_profit).toFixed(2)}</span>
                  </p>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      {/* Balance Sheet */}
      {tab === 'balance-sheet' ? (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <label className="text-sm text-muted-foreground">As of Date:</label>
            <input
              type="date"
              value={bsDate}
              onChange={(e) => setBsDate(e.target.value)}
              className="rounded-md border px-3 py-1.5 text-sm"
            />
            <button
              onClick={fetchBS}
              className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground"
            >
              Refresh
            </button>
          </div>

          {bsError ? <ErrorBox message={bsError} onRetry={fetchBS} /> : null}

          {bsLoading ? (
            <Spinner />
          ) : bsData ? (
            <div className="space-y-4">
              {/* Summary cards */}
              <div className="grid grid-cols-4 gap-4">
                <div className="rounded-lg border p-4">
                  <p className="text-xs text-muted-foreground">Total Assets</p>
                  <p className="text-lg font-semibold">
                    AED {Number(bsData.assets).toFixed(2)}
                  </p>
                </div>
                <div className="rounded-lg border p-4">
                  <p className="text-xs text-muted-foreground">Total Liabilities</p>
                  <p className="text-lg font-semibold">
                    AED {Number(bsData.liabilities).toFixed(2)}
                  </p>
                </div>
                <div className="rounded-lg border p-4">
                  <p className="text-xs text-muted-foreground">Total Equity</p>
                  <p className="text-lg font-semibold">
                    AED {Number(bsData.equity).toFixed(2)}
                  </p>
                </div>
                <div className="rounded-lg border p-4">
                  <p className="text-xs text-muted-foreground">Retained Earnings</p>
                  <p className="text-lg font-semibold">
                    AED {Number(bsData.retained_earnings).toFixed(2)}
                  </p>
                </div>
              </div>

              {/* Section breakdowns — optional, the API may omit them */}
              {(bsData.sections ?? []).map((section, si) => (
                <div key={si} className="rounded-lg border bg-white p-6">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold">{section.label}</h3>
                    <span className="text-sm font-medium">
                      AED {Number(section.total).toFixed(2)}
                    </span>
                  </div>
                  <div className="mt-3 overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="border-b text-left text-xs font-medium text-muted-foreground">
                        <tr>
                          <th className="px-3 py-2">Code</th>
                          <th className="px-3 py-2">Name</th>
                          <th className="px-3 py-2 text-right">Balance</th>
                        </tr>
                      </thead>
                      <tbody>
                        {section.accounts.map((a, ai) => (
                          <tr key={ai} className="border-b">
                            <td className="px-3 py-2 font-mono text-xs">{a.code}</td>
                            <td className="px-3 py-2">{a.name}</td>
                            <td className="px-3 py-2 text-right">
                              AED {Number(a.balance).toFixed(2)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}

              {/* Check equation */}
              <div className="rounded-lg border bg-white p-4 text-sm">
                <p className="text-muted-foreground">
                  Assets = Liabilities + Equity
                </p>
                <p className="mt-1 font-mono">
                  {Number(bsData.assets).toFixed(2)} ={' '}
                  {Number(bsData.liabilities).toFixed(2)} +{' '}
                  {Number(bsData.equity).toFixed(2)} ={' '}
                  {Number(bsData.total_liabilities_and_equity).toFixed(2)}
                </p>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function StatCard({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color: string;
}) {
  return (
    <div className="rounded-lg border p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={clsx('text-lg font-semibold', color)}>
        AED {Number(value).toFixed(2)}
      </p>
    </div>
  );
}
