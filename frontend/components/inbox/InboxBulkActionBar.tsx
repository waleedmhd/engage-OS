'use client';

import { useEffect, useState } from 'react';
import { X, Tag, Activity } from 'lucide-react';
import { Modal, Spinner } from '@/components/shared/ui';
import { listTags } from '@/lib/tags';
import { bulkUpdateConversations } from '@/lib/conversations';
import type {
  BulkActionResponse,
  ConversationStateWire,
  TagWithUsage,
} from '@/types/api';

const STATES: ConversationStateWire[] = [
  'NEW',
  'AI_ACTIVE',
  'AWAITING_APPROVAL',
  'HUMAN_ASSIGNED',
  'AI_PAUSED',
  'CLOSED',
];

interface InboxBulkActionBarProps {
  selectedIds: string[];
  onClear: () => void;
  onDone: (receipt: BulkActionResponse, action: string) => void;
}

type Dialog =
  | { kind: 'state'; value: ConversationStateWire }
  | { kind: 'add_tag'; tagId: string; tagName: string }
  | { kind: 'remove_tag'; tagId: string; tagName: string }
  | null;

export function InboxBulkActionBar({
  selectedIds,
  onClear,
  onDone,
}: InboxBulkActionBarProps) {
  const [tags, setTags] = useState<TagWithUsage[]>([]);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listTags()
      .then(setTags)
      .catch(() => setTags([]));
  }, []);

  if (selectedIds.length === 0) return null;
  const count = selectedIds.length;

  async function runUpdate(
    patch: Record<string, unknown>,
    label: string,
  ): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const receipt = await bulkUpdateConversations(selectedIds, patch);
      onDone(receipt, label);
      setDialog(null);
    } catch {
      setError('Bulk update failed.');
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
            <Activity className="h-3 w-3" /> State:
            <select
              defaultValue=""
              onChange={(e) => {
                if (!e.target.value) return;
                setDialog({
                  kind: 'state',
                  value: e.target.value as ConversationStateWire,
                });
                e.currentTarget.value = '';
              }}
              className="rounded-md border px-2 py-1 text-xs"
            >
              <option value="">—</option>
              {STATES.map((s) => (
                <option key={s} value={s}>
                  {s.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-1 text-xs">
            <Tag className="h-3 w-3" /> Add tag:
            <select
              defaultValue=""
              onChange={(e) => {
                if (!e.target.value) return;
                const tag = tags.find((t) => t.id === e.target.value);
                setDialog({
                  kind: 'add_tag',
                  tagId: e.target.value,
                  tagName: tag?.name ?? e.target.value,
                });
                e.currentTarget.value = '';
              }}
              disabled={tags.length === 0}
              className="rounded-md border px-2 py-1 text-xs disabled:opacity-50"
            >
              <option value="">—</option>
              {tags.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-1 text-xs">
            <Tag className="h-3 w-3" /> Remove tag:
            <select
              defaultValue=""
              onChange={(e) => {
                if (!e.target.value) return;
                const tag = tags.find((t) => t.id === e.target.value);
                setDialog({
                  kind: 'remove_tag',
                  tagId: e.target.value,
                  tagName: tag?.name ?? e.target.value,
                });
                e.currentTarget.value = '';
              }}
              disabled={tags.length === 0}
              className="rounded-md border px-2 py-1 text-xs disabled:opacity-50"
            >
              <option value="">—</option>
              {tags.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>

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
        title={`Update ${count} conversations?`}
      >
        {dialog ? (
          <div className="space-y-4 text-sm">
            {dialog.kind === 'state' ? (
              <p>
                Set state to <strong>{dialog.value.replace(/_/g, ' ')}</strong>{' '}
                for {count} conversations.
              </p>
            ) : dialog.kind === 'add_tag' ? (
              <p>
                Add tag <strong>{dialog.tagName}</strong> to {count}{' '}
                conversations.
              </p>
            ) : (
              <p>
                Remove tag <strong>{dialog.tagName}</strong> from {count}{' '}
                conversations.
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
                  if (dialog.kind === 'state') {
                    runUpdate({ state: dialog.value }, 'state');
                  } else if (dialog.kind === 'add_tag') {
                    runUpdate({ add_tag_ids: [dialog.tagId] }, 'add_tag');
                  } else {
                    runUpdate({ remove_tag_ids: [dialog.tagId] }, 'remove_tag');
                  }
                }}
                className="flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-60"
              >
                {busy ? <Spinner className="text-primary-foreground" /> : null}
                Confirm
              </button>
            </div>
          </div>
        ) : null}
      </Modal>
    </>
  );
}
