'use client';

import { useCallback, useEffect, useState } from 'react';
import { PageHeader } from '@/components/shared/PageHeader';
import {
  ErrorBox,
  Modal,
  Pagination,
  PermissionState,
  SkeletonRows,
} from '@/components/shared/ui';
import { fetchPage } from '@/lib/lists';
import { useAuth } from '@/hooks/useAuth';
import type { AuditAction, AuditLogResponse } from '@/types/api';

const PAGE_SIZE = 50;
const ACTIONS: AuditAction[] = [
  'create',
  'update',
  'delete',
  'login',
  'approve',
  'reject',
  'pause_ai',
  'resume_ai',
  'assign',
  'launch_campaign',
];

type FetchError = Error & { status?: number };

function fmt(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
}

function short(id?: string | null): string {
  if (!id) return '—';
  return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}

export default function AuditLogsPage() {
  const { user, isLoading: authLoading } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [items, setItems] = useState<AuditLogResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [action, setAction] = useState('');
  const [entityType, setEntityType] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [detail, setDetail] = useState<AuditLogResponse | null>(null);

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    setError(null);
    setForbidden(false);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
      });
      if (action) params.set('action', action);
      if (entityType) params.set('entity_type', entityType);
      const res = await fetchPage<AuditLogResponse>(
        `/audit-logs?${params.toString()}`,
      );
      setItems(res.items);
      setTotal(res.total);
    } catch (err) {
      if ((err as FetchError).status === 403) {
        setForbidden(true);
      } else {
        setError('Failed to load audit logs.');
      }
    } finally {
      setLoading(false);
    }
  }, [page, action, entityType]);

  useEffect(() => {
    if (isAdmin) fetchLogs();
  }, [isAdmin, fetchLogs]);

  if (authLoading) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Audit Logs"
          description="Immutable record of critical system actions (DSD §9)."
        />
        <SkeletonRows rows={6} />
      </div>
    );
  }

  if (!isAdmin || forbidden) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Audit Logs"
          description="Immutable record of critical system actions (DSD §9)."
        />
        <PermissionState title="Audit logs are admin-only" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Audit Logs"
        description="Immutable record of critical system actions (DSD §9)."
      />

      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground">
            Action
          </label>
          <select
            value={action}
            onChange={(e) => {
              setPage(1);
              setAction(e.target.value);
            }}
            className="rounded-md border px-3 py-2 text-sm"
          >
            <option value="">All actions</option>
            {ACTIONS.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground">
            Entity type
          </label>
          <input
            value={entityType}
            onChange={(e) => {
              setPage(1);
              setEntityType(e.target.value);
            }}
            placeholder="e.g. conversation"
            className="rounded-md border px-3 py-2 text-sm"
          />
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border bg-white">
        {loading ? (
          <div className="p-4">
            <SkeletonRows rows={8} />
          </div>
        ) : error ? (
          <div className="p-4">
            <ErrorBox message={error} onRetry={fetchLogs} />
          </div>
        ) : items.length === 0 ? (
          <p className="p-6 text-center text-sm text-muted-foreground">
            No audit entries found.
          </p>
        ) : (
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="border-b text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-3">Time</th>
                <th className="px-4 py-3">Actor</th>
                <th className="px-4 py-3">Action</th>
                <th className="px-4 py-3">Entity</th>
                <th className="px-4 py-3">Details</th>
              </tr>
            </thead>
            <tbody>
              {items.map((l) => (
                <tr key={l.id} className="border-b">
                  <td className="px-4 py-3 whitespace-nowrap">
                    {fmt(l.created_at)}
                  </td>
                  <td className="px-4 py-3">
                    <span className="capitalize">{l.actor_type}</span>
                    <span className="ml-1 font-mono text-xs text-muted-foreground">
                      {short(l.actor_id)}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-medium">{l.action}</td>
                  <td className="px-4 py-3">
                    <span>{l.entity_type}</span>
                    <span className="ml-1 font-mono text-xs text-muted-foreground">
                      {short(l.entity_id)}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => setDetail(l)}
                      className="rounded-md border px-2 py-1 text-xs hover:bg-muted"
                    >
                      Details
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {!loading && !error && items.length > 0 ? (
        <Pagination
          page={page}
          pageSize={PAGE_SIZE}
          total={total}
          onPage={setPage}
        />
      ) : null}

      <Modal
        open={Boolean(detail)}
        onClose={() => setDetail(null)}
        title="Audit Entry"
      >
        {detail ? (
          <div className="space-y-4 text-sm">
            <div className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-1">
              <span className="text-muted-foreground">Time</span>
              <span>{fmt(detail.created_at)}</span>
              <span className="text-muted-foreground">Actor</span>
              <span className="capitalize">
                {detail.actor_type}{' '}
                <span className="font-mono text-xs">{detail.actor_id ?? '—'}</span>
              </span>
              <span className="text-muted-foreground">Action</span>
              <span className="font-medium">{detail.action}</span>
              <span className="text-muted-foreground">Entity</span>
              <span>
                {detail.entity_type}{' '}
                <span className="font-mono text-xs">{detail.entity_id ?? '—'}</span>
              </span>
            </div>
            <div className="space-y-1">
              <p className="text-xs font-medium text-muted-foreground">
                Before
              </p>
              <pre className="max-h-48 overflow-auto rounded-md border bg-muted/50 p-3 text-xs">
                {detail.before_state
                  ? JSON.stringify(detail.before_state, null, 2)
                  : '—'}
              </pre>
            </div>
            <div className="space-y-1">
              <p className="text-xs font-medium text-muted-foreground">After</p>
              <pre className="max-h-48 overflow-auto rounded-md border bg-muted/50 p-3 text-xs">
                {detail.after_state
                  ? JSON.stringify(detail.after_state, null, 2)
                  : '—'}
              </pre>
            </div>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
