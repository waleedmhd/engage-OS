'use client';

import { Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeft, Pencil } from 'lucide-react';
import { useSearchParams } from 'next/navigation';
import { PageHeader } from '@/components/shared/PageHeader';
import { EmptyState } from '@/components/shared/EmptyState';
import {
  ErrorBox,
  Modal,
  SkeletonRows,
  Spinner,
  StateBadge,
} from '@/components/shared/ui';
import { NewMessageDialog } from '@/components/inbox/NewMessageDialog';
import { MessageBubble } from '@/components/inbox/MessageBubble';
import { Composer } from '@/components/inbox/Composer';
import { InboxBulkActionBar } from '@/components/inbox/InboxBulkActionBar';
import {
  ContactTagsEditor,
  TagChip,
} from '@/components/contacts/ContactTagsEditor';
import { AgentPicker, AI_AGENT_SENTINEL } from '@/components/contacts/AgentPicker';
import { authedFetch } from '@/lib/authedFetch';
import { fetchPage } from '@/lib/lists';
import { listTags } from '@/lib/tags';
import { updateContact, listUsers } from '@/lib/contacts';
import { useLiveEvents } from '@/hooks/useLiveEvents';
import { useAuth } from '@/hooks/useAuth';
import type {
  ContactResponse,
  ContactStatus,
  ContactUpdateRequest,
  ConversationListItem,
  ConversationResponse,
  ConversationStateWire,
  MessageResponse,
  TagWithUsage,
  UserResponse,
} from '@/types/api';

const STATES: ConversationStateWire[] = [
  'NEW',
  'AI_ACTIVE',
  'AWAITING_APPROVAL',
  'HUMAN_ASSIGNED',
  'AI_PAUSED',
  'CLOSED',
];

function fmtTime(iso?: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function InboxPage() {
  return (
    <Suspense fallback={<SkeletonRows rows={8} />}>
      <InboxPageInner />
    </Suspense>
  );
}

function InboxPageInner() {
  const searchParams = useSearchParams();

  const [list, setList] = useState<ConversationListItem[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const [stateFilter, setStateFilter] = useState(searchParams.get('state') ?? '');
  const [tagFilter, setTagFilter] = useState('');
  const [tags, setTags] = useState<TagWithUsage[]>([]);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [conversation, setConversation] = useState<ConversationResponse | null>(
    null,
  );
  const [messages, setMessages] = useState<MessageResponse[]>([]);
  const [threadLoading, setThreadLoading] = useState(false);
  const [threadError, setThreadError] = useState<string | null>(null);

  const [actionBusy, setActionBusy] = useState(false);
  const [newMsgOpen, setNewMsgOpen] = useState(false);

  // Reply & forward state
  const [replyTo, setReplyTo] = useState<{ id: string; content: string; isOutbound: boolean } | null>(null);
  const [forwardMsgId, setForwardMsgId] = useState<string | null>(null);
  const [forwardOpen, setForwardOpen] = useState(false);
  const [forwardTargetId, setForwardTargetId] = useState<string | null>(null);

  // Selection mode (batch 3)
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedMsgIds, setSelectedMsgIds] = useState<Set<string>>(new Set());
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [bulkActionBusy, setBulkActionBusy] = useState(false);

  // Contact edit
  const [editContactOpen, setEditContactOpen] = useState(false);
  const [contactForm, setContactForm] = useState<ContactUpdateRequest>({});
  const [contactSaving, setContactSaving] = useState(false);
  const [contactError, setContactError] = useState<string | null>(null);
  const [users, setUsers] = useState<UserResponse[] | null>(null);
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  // Conversation multi-select
  const [selectedConvIds, setSelectedConvIds] = useState<Set<string>>(new Set());
  const [bulkReceipt, setBulkReceipt] = useState<{
    action: string;
    receipt: { count: number; failed: { id: string; error: string }[] };
  } | null>(null);

  // Clear selection when filters/search change so stale IDs aren't carried
  // into a new page of results.
  useEffect(() => {
    setSelectedConvIds(new Set());
  }, [q, stateFilter, tagFilter]);

  const threadEndRef = useRef<HTMLDivElement>(null);

  const fetchList = useCallback(
    async (opts?: { silent?: boolean }) => {
      // Background refreshes (live events, post-send) skip the skeleton so the
      // list re-orders smoothly instead of flashing — only the first load and
      // search/filter changes show the loading state.
      if (!opts?.silent) setListLoading(true);
      setListError(null);
      try {
        const params = new URLSearchParams({ page: '1', page_size: '50' });
        if (q) params.set('q', q);
        if (stateFilter) params.set('state', stateFilter);
        if (tagFilter) params.set('tag_id', tagFilter);
        const res = await fetchPage<ConversationListItem>(
          `/conversations?${params.toString()}`,
        );
        setList(res.items);
      } catch {
        if (!opts?.silent) setListError('Failed to load conversations.');
      } finally {
        if (!opts?.silent) setListLoading(false);
      }
    },
    [q, stateFilter, tagFilter],
  );

  useEffect(() => {
    fetchList();
  }, [fetchList]);

  // Load the tag taxonomy once for the filter dropdown; tolerate failure so the
  // inbox still works without tag options.
  useEffect(() => {
    listTags()
      .then(setTags)
      .catch(() => setTags([]));
  }, []);

  useLiveEvents<{ event?: string; conversation_id?: string }>(
    '/inbox',
    (evt) => {
      // Any inbox event means "something changed" — silently refresh the list
      // preview so it re-orders (most-recent-first) without a skeleton flash.
      fetchList({ silent: true });
      // If the change touched the conversation currently open, re-pull its
      // thread too so inbound/outbound messages appear without a page refresh.
      if (
        selectedId &&
        (!evt?.conversation_id || evt.conversation_id === selectedId)
      ) {
        loadThread(selectedId);
      }
    },
  );

  const loadThread = useCallback(async (id: string) => {
    setThreadLoading(true);
    setThreadError(null);
    try {
      const [conv, msgs] = await Promise.all([
        authedFetch<ConversationResponse>(`/conversations/${id}`),
        fetchPage<MessageResponse>(`/messages/${id}?limit=50&offset=0`),
      ]);
      setConversation(conv);
      setMessages(msgs.items);
      // Optimistically clear unread on the list row so the UI updates
      // immediately — the backend already set last_read_at on the GET.
      setList((prev) =>
        prev.map((c) => (c.id === id ? { ...c, unread: false } : c)),
      );
    } catch {
      setThreadError('Failed to load conversation.');
    } finally {
      setThreadLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedId) loadThread(selectedId);
  }, [selectedId, loadThread]);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView();
  }, [messages]);

  async function runAction(path: string) {
    if (!conversation) return;
    setActionBusy(true);
    try {
      await authedFetch(`/conversations/${conversation.id}/${path}`, {
        method: 'POST',
      });
      await loadThread(conversation.id);
      await fetchList();
    } catch {
      setThreadError('Action failed.');
    } finally {
      setActionBusy(false);
    }
  }

  async function transitionState(targetState: ConversationStateWire) {
    if (!conversation) return;
    setActionBusy(true);
    try {
      await authedFetch(`/conversations/${conversation.id}/transition`, {
        method: 'POST',
        json: { target_state: targetState },
      });
      await loadThread(conversation.id);
      await fetchList();
    } catch {
      setThreadError('State change failed.');
    } finally {
      setActionBusy(false);
    }
  }

  async function openEditContact() {
    if (!conversation) return;
    setContactError(null);
    setEditContactOpen(true);
    if (!users) listUsers().then(setUsers).catch(() => {});
    // Fetch full contact so we can pre-fill company/status/notes.
    try {
      const full = await authedFetch<ContactResponse>(
        `/contacts/${conversation.contact_id}`,
      );
      setContactForm({
        name: full.name,
        company: full.company,
        status: full.status,
        notes: full.notes,
        assigned_agent_id: full.ai_assigned
          ? AI_AGENT_SENTINEL
          : full.assigned_agent_id,
        ai_assigned: full.ai_assigned,
      });
    } catch {
      // If fetch fails, still allow editing with summary data.
      const c = conversation.contact;
      setContactForm({
        name: c?.name ?? null,
        company: null,
        status: undefined,
        notes: null,
        assigned_agent_id: c?.ai_assigned
          ? AI_AGENT_SENTINEL
          : (c?.assigned_agent_id ?? null),
        ai_assigned: c?.ai_assigned ?? false,
      });
    }
  }

  async function saveContact(e: React.FormEvent) {
    e.preventDefault();
    if (!conversation) return;
    setContactSaving(true);
    setContactError(null);
    try {
      const isAI = contactForm.ai_assigned;
      const updated = await updateContact(conversation.contact_id, {
        ...contactForm,
        assigned_agent_id: isAI ? null : (contactForm.assigned_agent_id ?? null),
        ai_assigned: isAI ? true : (contactForm.ai_assigned ?? false),
      });
      setConversation((prev) =>
        prev
          ? {
              ...prev,
              contact: {
                id: updated.id,
                name: updated.name,
                phone: updated.phone,
                assigned_agent_id: updated.assigned_agent_id,
                ai_assigned: updated.ai_assigned,
              },
            }
          : prev,
      );
      setEditContactOpen(false);
      fetchList();
    } catch {
      setContactError('Failed to save contact.');
    } finally {
      setContactSaving(false);
    }
  }

  const handleMessageSent = useCallback(
    (reply: MessageResponse) => {
      setMessages((prev) => {
        const idx = prev.findIndex((m) => m.id === reply.id);
        if (idx >= 0) {
          return prev.map((m) => (m.id === reply.id ? reply : m));
        }
        return [...prev, reply];
      });
      // WhatsApp-style reorder: float the conversation to the top.
      const now = new Date().toISOString();
      setList((prev) => {
        if (!conversation) return prev;
        const idx = prev.findIndex((c) => c.id === conversation.id);
        if (idx === -1) return prev;
        const moved: ConversationListItem = {
          ...prev[idx],
          last_message_at: now,
          unread: false,
          last_message: {
            id: reply.id,
            direction: 'OUTBOUND',
            content: reply.content,
            created_at: now,
          },
        };
        return [moved, ...prev.filter((_, i) => i !== idx)];
      });
    },
    [conversation],
  );

  const handleReply = useCallback((msg: MessageResponse) => {
    const isOutbound = String(msg.direction).toUpperCase() === 'OUTBOUND';
    setReplyTo({ id: msg.id, content: msg.content, isOutbound });
  }, []);

  const handleForward = useCallback((msg: MessageResponse) => {
    setForwardMsgId(msg.id);
    setForwardOpen(true);
  }, []);

  // --- selection mode handlers ---

  function enterSelectionMode() {
    setSelectedMsgIds(new Set());
    setSelectionMode(true);
  }

  function exitSelectionMode() {
    setSelectedMsgIds(new Set());
    setSelectionMode(false);
  }

  const toggleSelectMsg = useCallback((id: string) => {
    setSelectedMsgIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleDeleteThis = useCallback((msg: MessageResponse) => {
    // Single delete: enter selection mode with just this message, then open confirm.
    setSelectedMsgIds(new Set([msg.id]));
    setSelectionMode(true);
    setDeleteConfirmOpen(true);
  }, []);

  // --- bulk actions ---

  const handleBulkCopy = useCallback(() => {
    const parts: string[] = [];
    for (const m of messages) {
      if (selectedMsgIds.has(m.id)) {
        if (m.msg_type === 'text') {
          parts.push(m.content);
        } else if (m.msg_type === 'image') parts.push('[Image]');
        else if (m.msg_type === 'video') parts.push('[Video]');
        else if (m.msg_type === 'audio') parts.push('[Audio]');
        else if (m.msg_type === 'contact') parts.push('[Contact]');
        else parts.push(m.content);
      }
    }
    navigator.clipboard.writeText(parts.join('\n')).catch(() => {});
    exitSelectionMode();
  }, [messages, selectedMsgIds]);

  // Bulk forward uses the same forward modal but for bulk
  const [bulkForwardOpen, setBulkForwardOpen] = useState(false);
  const [bulkForwardTargetId, setBulkForwardTargetId] = useState<string | null>(null);

  const handleBulkForward = useCallback(() => {
    setBulkForwardOpen(true);
    setBulkForwardTargetId(null);
  }, []);

  async function executeBulkForward() {
    if (!bulkForwardTargetId || selectedMsgIds.size === 0) return;
    setBulkActionBusy(true);
    try {
      await authedFetch<{ count: number; errors: string[] }>('/messages/bulk-forward', {
        method: 'POST',
        json: {
          message_ids: [...selectedMsgIds],
          target_conversation_id: bulkForwardTargetId,
        },
      });
      setBulkForwardOpen(false);
      setBulkForwardTargetId(null);
      exitSelectionMode();
      // Navigate to target so agent sees the forwarded copies.
      setSelectedId(bulkForwardTargetId);
      await fetchList();
    } catch {
      setThreadError('Failed to forward messages.');
    } finally {
      setBulkActionBusy(false);
    }
  }

  async function executeBulkDelete(scope: 'for_me' | 'for_everyone') {
    if (selectedMsgIds.size === 0) return;
    setBulkActionBusy(true);
    setDeleteConfirmOpen(false);
    try {
      await authedFetch<{ count: number; errors: string[] }>('/messages/bulk-delete', {
        method: 'POST',
        json: {
          message_ids: [...selectedMsgIds],
          scope,
        },
      });
      exitSelectionMode();
      if (conversation) await loadThread(conversation.id);
    } catch {
      setThreadError('Failed to delete messages.');
    } finally {
      setBulkActionBusy(false);
    }
  }

  async function executeForward() {
    if (!forwardMsgId || !forwardTargetId) return;
    try {
      const sent = await authedFetch<MessageResponse>(`/messages/${forwardMsgId}/forward`, {
        method: 'POST',
        json: { target_conversation_id: forwardTargetId },
      });
      setForwardOpen(false);
      setForwardMsgId(null);
      setForwardTargetId(null);
      // Navigate to the target conversation so the agent sees the forwarded message.
      setSelectedId(forwardTargetId);
      await fetchList();
    } catch {
      setThreadError('Failed to forward message.');
    }
  }

  const state = conversation?.state;
  const isClosed = state === 'CLOSED';

  return (
    <div className="space-y-4">
      <PageHeader
        title="Inbox"
        description="Live WhatsApp conversations with AI status, takeover, and quick reply."
      />

      {/* New message dialog — rendered at page root so it overlays everything */}
      <NewMessageDialog
        open={newMsgOpen}
        onClose={() => setNewMsgOpen(false)}
        onStarted={(id) => {
          setNewMsgOpen(false);
          fetchList();
          setSelectedId(id);
        }}
      />

      {/* Forward modal (single message) */}
      {forwardOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setForwardOpen(false)}>
          <div className="w-full max-w-sm rounded-lg bg-white shadow-xl mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="border-b px-4 py-3 font-medium text-sm">Forward message to...</div>
            <div className="max-h-80 overflow-y-auto">
              {list.filter((c) => c.id !== selectedId).length === 0 ? (
                <p className="px-4 py-6 text-center text-sm text-gray-500">No other conversations.</p>
              ) : (
                list.filter((c) => c.id !== selectedId).map((c) => (
                  <button
                    key={c.id}
                    onClick={() => setForwardTargetId(c.id)}
                    className={`w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-gray-50 ${
                      forwardTargetId === c.id ? 'bg-green-50' : ''
                    }`}
                  >
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-200 text-xs font-medium">
                      {(c.contact.name || c.contact.phone).charAt(0).toUpperCase()}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium truncate">
                        {c.contact.name || c.contact.phone}
                      </div>
                      <div className="text-xs text-gray-500">
                        {c.last_message?.content ?? 'No messages'}
                      </div>
                    </div>
                    {forwardTargetId === c.id && (
                      <span className="text-green-600 text-lg">✓</span>
                    )}
                  </button>
                ))
              )}
            </div>
            <div className="flex justify-end gap-2 border-t px-4 py-3">
              <button
                onClick={() => { setForwardOpen(false); setForwardMsgId(null); setForwardTargetId(null); }}
                className="rounded-md px-3 py-1.5 text-sm hover:bg-gray-100"
              >
                Cancel
              </button>
              <button
                disabled={!forwardTargetId}
                onClick={executeForward}
                className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-50"
              >
                Forward
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Bulk forward modal */}
      {bulkForwardOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setBulkForwardOpen(false)}>
          <div className="w-full max-w-sm rounded-lg bg-white shadow-xl mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="border-b px-4 py-3 font-medium text-sm">
              Forward {selectedMsgIds.size} message{selectedMsgIds.size > 1 ? 's' : ''} to...
            </div>
            <div className="max-h-80 overflow-y-auto">
              {list.filter((c) => c.id !== selectedId).length === 0 ? (
                <p className="px-4 py-6 text-center text-sm text-gray-500">No other conversations.</p>
              ) : (
                list.filter((c) => c.id !== selectedId).map((c) => (
                  <button
                    key={c.id}
                    onClick={() => setBulkForwardTargetId(c.id)}
                    className={`w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-gray-50 ${
                      bulkForwardTargetId === c.id ? 'bg-green-50' : ''
                    }`}
                  >
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-200 text-xs font-medium">
                      {(c.contact.name || c.contact.phone).charAt(0).toUpperCase()}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium truncate">{c.contact.name || c.contact.phone}</div>
                      <div className="text-xs text-gray-500">{c.last_message?.content ?? 'No messages'}</div>
                    </div>
                    {bulkForwardTargetId === c.id && (
                      <span className="text-green-600 text-lg">✓</span>
                    )}
                  </button>
                ))
              )}
            </div>
            <div className="flex justify-end gap-2 border-t px-4 py-3">
              <button
                onClick={() => { setBulkForwardOpen(false); setBulkForwardTargetId(null); }}
                className="rounded-md px-3 py-1.5 text-sm hover:bg-gray-100"
              >
                Cancel
              </button>
              <button
                disabled={!bulkForwardTargetId || bulkActionBusy}
                onClick={executeBulkForward}
                className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-50"
              >
                Forward
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation modal */}
      {deleteConfirmOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setDeleteConfirmOpen(false)}>
          <div className="w-full max-w-sm rounded-lg bg-white shadow-xl mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-5">
              <h3 className="text-base font-medium mb-4">
                Delete {selectedMsgIds.size} message{selectedMsgIds.size > 1 ? 's' : ''}?
              </h3>
              <div className="flex flex-col gap-2">
                <button
                  onClick={() => executeBulkDelete('for_me')}
                  disabled={bulkActionBusy}
                  className="w-full text-left px-4 py-3 rounded-lg border hover:bg-gray-50 disabled:opacity-50"
                >
                  <div className="text-sm font-medium">Delete for me</div>
                  <div className="text-xs text-gray-500">Remove from your view. Others will still see them.</div>
                </button>
                <button
                  onClick={() => executeBulkDelete('for_everyone')}
                  disabled={bulkActionBusy}
                  className="w-full text-left px-4 py-3 rounded-lg border hover:bg-red-50 disabled:opacity-50"
                >
                  <div className="text-sm font-medium text-red-700">Delete for everyone</div>
                  <div className="text-xs text-gray-500">Send delete request to WhatsApp. May not succeed for old messages.</div>
                </button>
              </div>
              <div className="text-right mt-4">
                <button onClick={() => setDeleteConfirmOpen(false)} className="rounded-md px-3 py-1.5 text-sm hover:bg-gray-100">Cancel</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Edit contact modal */}
      <Modal
        open={editContactOpen}
        onClose={() => setEditContactOpen(false)}
        title="Edit Contact"
      >
        <form onSubmit={saveContact} className="space-y-4 text-sm">
          {contactError ? <ErrorBox message={contactError} /> : null}
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Name</label>
            <input
              value={contactForm.name ?? ''}
              onChange={(e) => setContactForm({ ...contactForm, name: e.target.value })}
              className="w-full rounded-md border px-3 py-2"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Company</label>
            <input
              value={contactForm.company ?? ''}
              onChange={(e) => setContactForm({ ...contactForm, company: e.target.value })}
              className="w-full rounded-md border px-3 py-2"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Status</label>
            <select
              value={contactForm.status ?? ''}
              onChange={(e) =>
                setContactForm({
                  ...contactForm,
                  status: (e.target.value || undefined) as ContactStatus | undefined,
                })
              }
              className="w-full rounded-md border px-3 py-2"
            >
              <option value="">(unchanged)</option>
              {(['active', 'contacted', 'follow_up', 'interested', 'not_interested', 'inactive', 'blocked'] as ContactStatus[]).map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Notes</label>
            <textarea
              value={contactForm.notes ?? ''}
              onChange={(e) => setContactForm({ ...contactForm, notes: e.target.value })}
              rows={3}
              className="w-full resize-none rounded-md border px-3 py-2"
            />
          </div>
          {users ? (
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Assigned Agent</label>
              <AgentPicker
                users={users}
                includeUnassigned
                includeAI
                value={
                  contactForm.ai_assigned
                    ? AI_AGENT_SENTINEL
                    : (contactForm.assigned_agent_id || null)
                }
                onChange={(v) =>
                  setContactForm({
                    ...contactForm,
                    assigned_agent_id:
                      v === AI_AGENT_SENTINEL ? null : v,
                    ai_assigned: v === AI_AGENT_SENTINEL,
                  })
                }
                className="w-full"
              />
            </div>
          ) : null}
          <button
            type="submit"
            disabled={contactSaving}
            className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 font-medium text-primary-foreground disabled:opacity-60"
          >
            {contactSaving ? <Spinner className="text-primary-foreground" /> : null}
            Save Contact
          </button>
        </form>
      </Modal>

      <div className="flex h-[calc(100vh-180px)] flex-col gap-4 md:h-[calc(100vh-220px)] md:flex-row">
        {/* Left: conversation list */}
        <div
          className={`min-h-0 flex-col rounded-lg border bg-white md:flex md:w-80 ${
            selectedId ? 'hidden' : 'flex'
          }`}
        >
          <div className="space-y-2 border-b p-3">
            <div className="flex items-center gap-2">
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search…"
                className="min-w-0 flex-1 rounded-md border px-2 py-1.5 text-sm outline-none focus:border-primary"
              />
              <button
                onClick={() => setNewMsgOpen(true)}
                title="New message"
                className="shrink-0 rounded-md bg-primary px-2.5 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
              >
                + New
              </button>
            </div>
            <select
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value)}
              className="w-full rounded-md border px-2 py-1.5 text-sm outline-none"
            >
              <option value="">All states</option>
              {STATES.map((s) => (
                <option key={s} value={s}>
                  {s.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
            <select
              value={tagFilter}
              onChange={(e) => setTagFilter(e.target.value)}
              className="w-full rounded-md border px-2 py-1.5 text-sm outline-none"
            >
              <option value="">All tags</option>
              {tags.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </div>
          <div className="flex-1 overflow-y-auto p-2">
            <InboxBulkActionBar
              selectedIds={Array.from(selectedConvIds)}
              onClear={() => setSelectedConvIds(new Set())}
              onDone={(receipt, action) => {
                setBulkReceipt({ action, receipt });
                setSelectedConvIds(new Set());
                fetchList();
              }}
            />

            {bulkReceipt && (
              <div className="mx-1 mb-2 rounded-md border bg-green-50 px-3 py-2 text-xs text-green-800">
                {bulkReceipt.action === 'state'
                  ? 'State updated'
                  : bulkReceipt.action === 'add_tag'
                    ? 'Tag added'
                    : 'Tag removed'}
                {' for '}
                <strong>{bulkReceipt.receipt.count}</strong> conversation
                {bulkReceipt.receipt.count !== 1 ? 's' : ''}.
                {bulkReceipt.receipt.failed.length > 0 && (
                  <span className="text-red-700">
                    {' '}
                    {bulkReceipt.receipt.failed.length} failed.
                  </span>
                )}
                <button
                  onClick={() => setBulkReceipt(null)}
                  className="ml-2 underline"
                >
                  Dismiss
                </button>
              </div>
            )}

            {listLoading ? (
              <SkeletonRows rows={8} />
            ) : listError ? (
              <ErrorBox message={listError} onRetry={fetchList} />
            ) : list.length === 0 ? (
              <p className="px-2 py-6 text-center text-sm text-muted-foreground">
                No conversations.
              </p>
            ) : (
              <ul className="space-y-1">
                {list.map((c) => {
                  const isSelected = selectedConvIds.has(c.id);
                  return (
                    <li key={c.id} className="flex items-center gap-1">
                      <input
                        type="checkbox"
                        aria-label={`Select conversation with ${c.contact.name || c.contact.phone}`}
                        checked={isSelected}
                        onChange={() => {
                          setSelectedConvIds((prev) => {
                            const next = new Set(prev);
                            if (next.has(c.id)) next.delete(c.id);
                            else next.add(c.id);
                            return next;
                          });
                        }}
                        className="ml-2 h-4 w-4 shrink-0 rounded border-gray-300"
                      />
                      <button
                        onClick={() => setSelectedId(c.id)}
                        className={`flex-1 rounded-md px-2 py-2 text-left transition-colors ${
                          selectedId === c.id ? 'bg-accent' : 'hover:bg-muted'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span
                            className={`truncate text-sm ${
                              c.unread ? 'font-semibold' : 'font-medium'
                            }`}
                          >
                            {c.contact.name || c.contact.phone}
                          </span>
                          <span className="flex items-center gap-1.5">
                            {c.unread && (
                              <span className="h-2 w-2 rounded-full bg-blue-500" />
                            )}
                            <StateBadge state={c.state} />
                          </span>
                        </div>
                        <p
                          className={`mt-1 truncate text-xs ${
                            c.unread
                              ? 'text-foreground'
                              : 'text-muted-foreground'
                          }`}
                        >
                          {c.last_message?.content ?? 'No messages yet'}
                        </p>
                        <p className="mt-0.5 text-[11px] text-muted-foreground">
                          {fmtTime(c.last_message_at)}
                        </p>
                        {c.tags && c.tags.length > 0 && (
                          <div className="mt-1 flex flex-wrap gap-1">
                            {c.tags.map((t) => (
                              <TagChip key={t.id} tag={t} />
                            ))}
                          </div>
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>

        {/* Right: thread */}
        <div
          className={`min-h-0 flex-1 flex-col rounded-lg border bg-white md:flex ${
            selectedId ? 'flex' : 'hidden md:flex'
          }`}
        >
          {!selectedId ? (
            <div className="flex flex-1 items-center justify-center">
              <EmptyState
                title="Select a conversation"
                description="Pick a conversation from the list to view the message thread."
              />
            </div>
          ) : threadLoading ? (
            <div className="p-4">
              <SkeletonRows rows={8} />
            </div>
          ) : threadError ? (
            <div className="p-4">
              <ErrorBox
                message={threadError}
                onRetry={() => selectedId && loadThread(selectedId)}
              />
            </div>
          ) : conversation ? (
            <>
              {/* Action bar OR selection bar */}
              {selectionMode ? (
                <div className="flex items-center justify-between border-b bg-blue-600 text-white px-4 py-3">
                  <div className="flex items-center gap-3">
                    <button onClick={exitSelectionMode} className="text-white text-lg">&times;</button>
                    <span className="text-sm font-medium">{selectedMsgIds.size} selected</span>
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex items-center justify-between border-b px-4 py-3">
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => setSelectedId(null)}
                        className="-ml-1 rounded-md p-1 text-muted-foreground hover:bg-muted md:hidden"
                        aria-label="Back to conversations"
                      >
                        <ArrowLeft className="h-4 w-4" />
                      </button>
                      <StateBadge state={conversation.state} />
                    </div>
                    <div className="flex gap-2">
                      {isAdmin &&
                        conversation.allowed_transitions &&
                        conversation.allowed_transitions.length > 0 && (
                          <select
                            disabled={actionBusy}
                            value=""
                            onChange={(e) => {
                              if (e.target.value) {
                                transitionState(
                                  e.target.value as ConversationStateWire,
                                );
                              }
                            }}
                            className="rounded-md border px-2 py-1 text-xs font-medium text-muted-foreground hover:text-foreground disabled:opacity-50"
                          >
                            <option value="" disabled>
                              Change state…
                            </option>
                            {conversation.allowed_transitions.map((s) => (
                              <option key={s} value={s}>
                                {s.replace(/_/g, ' ')}
                              </option>
                            ))}
                          </select>
                        )}
                      {state === 'AI_ACTIVE' && (
                        <button
                          disabled={actionBusy}
                          onClick={() => runAction('pause-ai')}
                          className="rounded-md border px-3 py-1 text-xs font-medium hover:bg-muted disabled:opacity-50"
                        >
                          Pause AI
                        </button>
                      )}
                      {state === 'AI_PAUSED' && (
                        <button
                          disabled={actionBusy}
                          onClick={() => runAction('resume-ai')}
                          className="rounded-md border px-3 py-1 text-xs font-medium hover:bg-muted disabled:opacity-50"
                        >
                          Resume AI
                        </button>
                      )}
                      {state === 'AWAITING_APPROVAL' && (
                        <>
                          <button
                            disabled={actionBusy}
                            onClick={() => runAction('approve')}
                            className="rounded-md bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
                          >
                            Approve
                          </button>
                          <button
                            disabled={actionBusy}
                            onClick={() => runAction('reject')}
                            className="rounded-md bg-red-600 px-3 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
                          >
                            Reject
                          </button>
                        </>
                      )}
                      {!isClosed && (
                        <button
                          disabled={actionBusy}
                          onClick={() => runAction('close')}
                          className="rounded-md border px-3 py-1 text-xs font-medium hover:bg-muted disabled:opacity-50"
                        >
                          Close
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Contact info + tags */}
                  <div className="border-b px-4 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-sm font-medium">
                            {conversation.contact?.name || conversation.contact?.phone || 'Unknown'}
                          </span>
                          {conversation.contact?.name && conversation.contact?.phone ? (
                            <span className="text-xs text-muted-foreground">
                              {conversation.contact.phone}
                            </span>
                          ) : null}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={openEditContact}
                        className="flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
                      >
                        <Pencil className="h-3 w-3" />
                        Edit
                      </button>
                    </div>
                    <div className="mt-1">
                      <ContactTagsEditor contactId={conversation.contact_id} />
                    </div>
                  </div>
                </>
              )}

              {/* Messages */}
              <div className="flex-1 space-y-1.5 overflow-y-auto bg-[#efeae2] p-4">
                {messages.length === 0 ? (
                  <p className="text-center text-sm text-muted-foreground">
                    No messages yet.
                  </p>
                ) : (
                  messages.map((m) => (
                    <MessageBubble
                      key={m.id}
                      message={m}
                      onReply={handleReply}
                      onForward={handleForward}
                      onDelete={handleDeleteThis}
                      onSelect={() => { enterSelectionMode(); toggleSelectMsg(m.id); }}
                      selectionMode={selectionMode}
                      selected={selectedMsgIds.has(m.id)}
                      onToggleSelect={() => toggleSelectMsg(m.id)}
                    />
                  ))
                )}
                <div ref={threadEndRef} />
              </div>

              {/* Bottom bar: composer OR bulk action bar */}
              {selectionMode ? (
                <div className="flex items-center justify-center gap-4 border-t px-4 py-3 bg-white">
                  <button
                    onClick={handleBulkCopy}
                    disabled={selectedMsgIds.size === 0 || bulkActionBusy}
                    className="flex flex-col items-center gap-1 rounded-lg px-4 py-2 text-xs font-medium text-gray-700 hover:bg-gray-100 disabled:opacity-40"
                  >
                    <span className="text-lg">📋</span> Copy
                  </button>
                  <button
                    onClick={handleBulkForward}
                    disabled={selectedMsgIds.size === 0 || bulkActionBusy}
                    className="flex flex-col items-center gap-1 rounded-lg px-4 py-2 text-xs font-medium text-gray-700 hover:bg-gray-100 disabled:opacity-40"
                  >
                    <span className="text-lg">➡️</span> Forward
                  </button>
                  <button
                    onClick={() => setDeleteConfirmOpen(true)}
                    disabled={selectedMsgIds.size === 0 || bulkActionBusy}
                    className="flex flex-col items-center gap-1 rounded-lg px-4 py-2 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-40"
                  >
                    <span className="text-lg">🗑️</span> Delete
                  </button>
                </div>
              ) : (
                !isClosed && conversation && (
                  <Composer
                    conversationId={conversation.id}
                    onMessageSent={handleMessageSent}
                    replyTo={replyTo}
                    onCancelReply={() => setReplyTo(null)}
                  />
                )
              )}
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
