'use client';

import { useEffect, useRef, useState } from 'react';
import { Search } from 'lucide-react';
import { Spinner } from '@/components/shared/ui';
import { Modal } from '@/components/shared/ui';
import { authedFetch } from '@/lib/authedFetch';
import { fetchPage } from '@/lib/lists';
import type {
  ContactResponse,
  StartConversationResponse,
  TemplateResponse,
} from '@/types/api';

interface NewMessageDialogProps {
  open: boolean;
  onClose: () => void;
  /** Called with the resolved/created conversation_id on success. */
  onStarted: (conversationId: string) => void;
}

export function NewMessageDialog({
  open,
  onClose,
  onStarted,
}: NewMessageDialogProps) {
  // ── Contact search ──────────────────────────────────────────────────────
  const [query, setQuery] = useState('');
  const [contacts, setContacts] = useState<ContactResponse[]>([]);
  const [contactsLoading, setContactsLoading] = useState(false);
  const [selectedContact, setSelectedContact] = useState<ContactResponse | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Templates ───────────────────────────────────────────────────────────
  const [templates, setTemplates] = useState<TemplateResponse[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [selectedTemplateId, setSelectedTemplateId] = useState('');

  // ── Send state ──────────────────────────────────────────────────────────
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── Fetch approved templates once on open ───────────────────────────────
  useEffect(() => {
    if (!open) return;
    setTemplatesLoading(true);
    fetchPage<TemplateResponse>('/templates?status=approved&page_size=100')
      .then(({ items }) => setTemplates(items))
      .catch(() => setTemplates([]))
      .finally(() => setTemplatesLoading(false));
  }, [open]);

  // ── Reset state when the dialog closes ──────────────────────────────────
  useEffect(() => {
    if (!open) {
      setQuery('');
      setContacts([]);
      setSelectedContact(null);
      setSelectedTemplateId('');
      setError(null);
    }
  }, [open]);

  // ── Debounced contact search ─────────────────────────────────────────────
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!query.trim()) {
      setContacts([]);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setContactsLoading(true);
      try {
        const params = new URLSearchParams({
          q: query.trim(),
          page: '1',
          page_size: '8',
        });
        const { items } = await fetchPage<ContactResponse>(
          `/contacts?${params.toString()}`,
        );
        setContacts(items);
      } catch {
        setContacts([]);
      } finally {
        setContactsLoading(false);
      }
    }, 300);
  }, [query]);

  // ── Send ────────────────────────────────────────────────────────────────
  async function handleSend() {
    if (!selectedContact || !selectedTemplateId) return;
    setSending(true);
    setError(null);
    try {
      const res = await authedFetch<StartConversationResponse>('/messages/start', {
        method: 'POST',
        json: { contact_id: selectedContact.id, template_id: selectedTemplateId },
      });
      onStarted(res.conversation_id);
    } catch (err: unknown) {
      const msg =
        err && typeof err === 'object' && 'message' in err
          ? String((err as { message: unknown }).message)
          : 'Failed to start conversation.';
      setError(msg);
    } finally {
      setSending(false);
    }
  }

  const canSend = !!selectedContact && !!selectedTemplateId && !sending;

  return (
    <Modal open={open} onClose={onClose} title="New message">
      <div className="space-y-5">

        {/* ── Contact picker ─────────────────────────────────────────────── */}
        <div className="space-y-2">
          <label className="text-sm font-medium text-gray-700">To</label>

          {selectedContact ? (
            <div className="flex items-center justify-between rounded-md border bg-green-50 px-3 py-2 text-sm">
              <span className="font-medium">
                {selectedContact.name || selectedContact.phone}
                {selectedContact.name && (
                  <span className="ml-1 text-xs text-gray-500">
                    ({selectedContact.phone})
                  </span>
                )}
              </span>
              <button
                onClick={() => {
                  setSelectedContact(null);
                  setQuery('');
                }}
                className="text-xs text-gray-500 hover:text-gray-800"
              >
                Change
              </button>
            </div>
          ) : (
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-gray-400" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search by name or phone…"
                className="w-full rounded-md border py-2 pl-8 pr-3 text-sm outline-none focus:border-primary"
              />
              {/* Results dropdown */}
              {(contactsLoading || contacts.length > 0) && (
                <div className="absolute z-10 mt-1 w-full rounded-md border bg-white shadow-lg">
                  {contactsLoading ? (
                    <div className="flex items-center gap-2 px-3 py-2 text-sm text-gray-500">
                      <Spinner /> Searching…
                    </div>
                  ) : (
                    <ul>
                      {contacts.map((c) => (
                        <li key={c.id}>
                          <button
                            className="w-full px-3 py-2 text-left text-sm hover:bg-muted"
                            onClick={() => {
                              setSelectedContact(c);
                              setQuery('');
                              setContacts([]);
                            }}
                          >
                            <span className="font-medium">
                              {c.name || c.phone}
                            </span>
                            {c.name && (
                              <span className="ml-1 text-xs text-gray-500">
                                {c.phone}
                              </span>
                            )}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
              {query.trim() && !contactsLoading && contacts.length === 0 && (
                <p className="mt-1 text-xs text-gray-500">No contacts found.</p>
              )}
            </div>
          )}
        </div>

        {/* ── Template picker ────────────────────────────────────────────── */}
        <div className="space-y-2">
          <label className="text-sm font-medium text-gray-700">
            Template
          </label>
          {templatesLoading ? (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Spinner /> Loading templates…
            </div>
          ) : templates.length === 0 ? (
            <p className="text-sm text-gray-500">
              No approved templates available. Ask an admin to submit and get a
              template approved in the Templates section.
            </p>
          ) : (
            <select
              value={selectedTemplateId}
              onChange={(e) => setSelectedTemplateId(e.target.value)}
              className="w-full rounded-md border px-3 py-2 text-sm outline-none focus:border-primary"
            >
              <option value="" disabled>
                Select a template…
              </option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                  {t.language !== 'en' ? ` (${t.language})` : ''}
                  {t.category ? ` — ${t.category}` : ''}
                </option>
              ))}
            </select>
          )}
        </div>

        {/* ── Error ──────────────────────────────────────────────────────── */}
        {error && (
          <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}

        {/* ── Actions ────────────────────────────────────────────────────── */}
        <div className="flex justify-end gap-2 pt-1">
          <button
            onClick={onClose}
            disabled={sending}
            className="rounded-md border px-4 py-2 text-sm font-medium hover:bg-muted disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSend}
            disabled={!canSend}
            className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {sending && <Spinner className="text-primary-foreground" />}
            Send
          </button>
        </div>
      </div>
    </Modal>
  );
}
