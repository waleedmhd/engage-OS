'use client';

import clsx from 'clsx';
import { Loader2, X } from 'lucide-react';
import type { ContactStatus, ConversationStateWire } from '@/types/api';

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx('h-4 w-4 animate-spin', className)} />;
}

export function SkeletonRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-10 w-full animate-pulse rounded-md bg-muted" />
      ))}
    </div>
  );
}

export function ErrorBox({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      <span>{message}</span>
      {onRetry ? (
        <button
          onClick={onRetry}
          className="rounded-md border border-red-300 bg-white px-3 py-1 text-xs font-medium text-red-700 hover:bg-red-100"
        >
          Retry
        </button>
      ) : null}
    </div>
  );
}

const STATE_STYLES: Record<ConversationStateWire, string> = {
  NEW: 'bg-gray-100 text-gray-700',
  AI_ACTIVE: 'bg-blue-100 text-blue-700',
  AWAITING_APPROVAL: 'bg-yellow-100 text-yellow-800',
  HUMAN_ASSIGNED: 'bg-green-100 text-green-700',
  AI_PAUSED: 'bg-orange-100 text-orange-700',
  CLOSED: 'bg-red-100 text-red-700',
};

export function StateBadge({ state }: { state: ConversationStateWire }) {
  return (
    <span
      className={clsx(
        'inline-block rounded-full px-2 py-0.5 text-[11px] font-medium',
        STATE_STYLES[state] ?? 'bg-gray-100 text-gray-700',
      )}
    >
      {state.replace(/_/g, ' ')}
    </span>
  );
}

const CONTACT_STATUS_STYLES: Record<ContactStatus, string> = {
  active: 'bg-blue-100 text-blue-700',
  contacted: 'bg-indigo-100 text-indigo-700',
  follow_up: 'bg-amber-100 text-amber-700',
  interested: 'bg-green-100 text-green-700',
  not_interested: 'bg-red-100 text-red-700',
  inactive: 'bg-gray-100 text-gray-700',
  blocked: 'bg-red-200 text-red-800',
};

export function ContactStatusBadge({ status }: { status: ContactStatus }) {
  return (
    <span
      className={clsx(
        'inline-block rounded-full px-2 py-0.5 text-xs font-medium',
        CONTACT_STATUS_STYLES[status] ?? 'bg-gray-100 text-gray-700',
      )}
    >
      {status.replace(/_/g, ' ')}
    </span>
  );
}

export function Modal({
  open,
  onClose,
  title,
  children,
  maxWidth = 'max-w-md',
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  maxWidth?: string;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex">
      <div
        className="flex-1 bg-black/30"
        onClick={onClose}
        aria-hidden="true"
      />
      <div className={`flex h-full w-full ${maxWidth} flex-col border-l bg-white shadow-xl`}>
        <div className="flex items-center justify-between border-b px-6 py-4">
          <h2 className="text-base font-semibold">{title}</h2>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-muted-foreground hover:bg-muted"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
      </div>
    </div>
  );
}

export function Pagination({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="flex items-center justify-between text-sm text-muted-foreground">
      <span>
        {total} total · page {page} of {totalPages}
      </span>
      <div className="flex gap-2">
        <button
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
          className="rounded-md border px-3 py-1 disabled:opacity-50"
        >
          Prev
        </button>
        <button
          disabled={page >= totalPages}
          onClick={() => onPage(page + 1)}
          className="rounded-md border px-3 py-1 disabled:opacity-50"
        >
          Next
        </button>
      </div>
    </div>
  );
}

export function PermissionState({ title }: { title: string }) {
  return (
    <div className="flex min-h-64 flex-col items-center justify-center rounded-lg border border-dashed bg-white px-6 py-12 text-center">
      <h2 className="text-base font-medium">{title}</h2>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">
        Insufficient permissions to view this content.
      </p>
    </div>
  );
}
