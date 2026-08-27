'use client';

import { useState } from 'react';
import { Trash2, UserCog, Activity, X } from 'lucide-react';
import { Modal, Spinner } from '@/components/shared/ui';
import { AgentPicker, AI_AGENT_SENTINEL } from '@/components/contacts/AgentPicker';
import {
  bulkDeleteContacts,
  bulkUpdateContacts,
} from '@/lib/contacts';
import type {
  BulkActionResponse,
  ContactStatus,
  UserResponse,
} from '@/types/api';

const STATUSES: ContactStatus[] = [
  'active',
  'contacted',
  'follow_up',
  'interested',
  'not_interested',
  'inactive',
  'blocked',
];

interface BulkActionBarProps {
  selectedIds: string[];
  isAdmin: boolean;
  users: UserResponse[] | null;
  onClear: () => void;
  onDone: (receipt: BulkActionResponse, action: string) => void;
}

type Dialog =
  | { kind: 'status'; value: ContactStatus }
  | { kind: 'agent'; value: string | null }
  | { kind: 'delete' }
  | null;

export function BulkActionBar({
  selectedIds,
  isAdmin,
  users,
  onClear,
  onDone,
}: BulkActionBarProps) {
  const [dialog, setDialog] = useState<Dialog>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (selectedIds.length === 0) return null;
  const count = selectedIds.length;

  async function runUpdate(
    patch: Record<string, unknown>,
    label: string,
  ): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const receipt = await bulkUpdateContacts({
        ids: selectedIds,
        patch,
      });
      onDone(receipt, label);
      setDialog(null);
    } catch {
      setError('Bulk update failed.');
    } finally {
      setBusy(false);
    }
  }

  async function runDelete(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const receipt = await bulkDeleteContacts(selectedIds);
      onDone(receipt, 'delete');
      setDialog(null);
    } catch {
      setError('Bulk delete failed.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="sticky top-0 z-10 flex flex-wrap items-center gap-2 rounded-md border bg-white p-3 shadow-sm">
        <span className="text-sm font-medium">{count} selected</span>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1 text-xs">
            <Activity className="h-3 w-3" /> Status:
            <select
              defaultValue=""
              onChange={(e) => {
                if (!e.target.value) return;
                setDialog({
                  kind: 'status',
                  value: e.target.value as ContactStatus,
                });
                e.currentTarget.value = '';
              }}
              className="rounded-md border px-2 py-1 text-xs"
            >
              <option value="">—</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>

          {isAdmin && users ? (
            <label className="flex items-center gap-1 text-xs">
              <UserCog className="h-3 w-3" /> Agent:
              <AgentPicker
                users={users}
                value={null}
                includeUnassigned
                includeAI
                onChange={(v) => setDialog({ kind: 'agent', value: v })}
                className="px-2 py-1 text-xs"
              />
            </label>
          ) : null}

          {isAdmin ? (
            <button
              onClick={() => setDialog({ kind: 'delete' })}
              className="flex items-center gap-1 rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700"
            >
              <Trash2 className="h-3 w-3" /> Delete
            </button>
          ) : null}

          <button
            onClick={onClear}
            className="flex items-center gap-1 rounded-md border px-2 py-1.5 text-xs text-muted-foreground hover:bg-muted"
          >
            <X className="h-3 w-3" /> Clear
          </button>
        </div>
      </div>

      <Modal
        open={dialog !== null}
        onClose={() => (busy ? undefined : setDialog(null))}
        title={
          dialog?.kind === 'delete'
            ? `Delete ${count} contacts?`
            : `Update ${count} contacts?`
        }
      >
        {dialog ? (
          <div className="space-y-4 text-sm">
            {dialog.kind === 'delete' ? (
              <p className="text-red-600">
                This permanently deletes {count} contacts. This cannot be
                undone.
              </p>
            ) : dialog.kind === 'status' ? (
              <p>
                Set <code>status</code> to <strong>{dialog.value}</strong> for{' '}
                {count} contacts.
              </p>
            ) : (
              <p>
                {dialog.value === null
                  ? `Unassign agent for ${count} contacts.`
                  : dialog.value === AI_AGENT_SENTINEL
                    ? `Assign ${count} contacts to AI Agent.`
                    : `Assign these ${count} contacts to the selected agent.`}
              </p>
            )}

            {error ? (
              <p className="rounded-md bg-red-50 px-3 py-2 text-red-700">
                {error}
              </p>
            ) : null}

            <div className="flex justify-end gap-2">
              <button
                disabled={busy}
                onClick={() => setDialog(null)}
                className="rounded-md border px-3 py-2 text-sm"
              >
                Cancel
              </button>
              <button
                disabled={busy}
                onClick={() => {
                  if (dialog.kind === 'delete') {
                    runDelete();
                  } else if (dialog.kind === 'status') {
                    runUpdate({ status: dialog.value }, 'status');
                  } else if (dialog.value === AI_AGENT_SENTINEL) {
                    runUpdate(
                      { ai_assigned: true, assigned_agent_id: null },
                      'assign',
                    );
                  } else {
                    runUpdate(
                      { assigned_agent_id: dialog.value },
                      'assign',
                    );
                  }
                }}
                className={`flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-white ${
                  dialog.kind === 'delete'
                    ? 'bg-red-600 hover:bg-red-700'
                    : 'bg-primary'
                } disabled:opacity-60`}
              >
                {busy ? <Spinner className="text-white" /> : null}
                Confirm
              </button>
            </div>
          </div>
        ) : null}
      </Modal>
    </>
  );
}
