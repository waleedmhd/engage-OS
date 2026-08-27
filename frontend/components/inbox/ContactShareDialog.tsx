'use client';

import { useEffect, useState } from 'react';
import { Search, Contact } from 'lucide-react';
import { authedFetch } from '@/lib/authedFetch';
import { fetchPage } from '@/lib/lists';
import type { ContactResponse } from '@/types/api';

export function ContactShareDialog({
  open,
  onClose,
  onSelect,
}: {
  open: boolean;
  onClose: () => void;
  onSelect: (contact: ContactResponse) => void;
}) {
  const [q, setQ] = useState('');
  const [contacts, setContacts] = useState<ContactResponse[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    const params = new URLSearchParams({ page: '1', page_size: '50' });
    if (q) params.set('q', q);
    fetchPage<ContactResponse>(`/contacts?${params.toString()}`)
      .then((res) => setContacts(res.items))
      .catch(() => setContacts([]))
      .finally(() => setLoading(false));
  }, [open, q]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="w-full max-w-sm rounded-lg bg-white shadow-xl mx-4" onClick={(e) => e.stopPropagation()}>
        <div className="border-b px-4 py-3 font-medium text-sm">Share a contact</div>
        <div className="px-4 py-2">
          <div className="flex items-center gap-2 rounded-md border px-2">
            <Search className="h-4 w-4 text-gray-400" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search contacts..."
              className="flex-1 py-2 text-sm outline-none"
              autoFocus
            />
          </div>
        </div>
        <div className="max-h-72 overflow-y-auto">
          {loading ? (
            <p className="px-4 py-6 text-center text-sm text-gray-500">Loading...</p>
          ) : contacts.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-gray-500">No contacts found.</p>
          ) : (
            contacts.map((c) => (
              <button
                key={c.id}
                onClick={() => {
                  onSelect(c);
                  onClose();
                }}
                className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-gray-50"
              >
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-100">
                  <Contact className="h-4 w-4 text-blue-600" />
                </div>
                <div className="min-w-0">
                  <div className="text-sm font-medium truncate">
                    {c.name || c.phone}
                  </div>
                  <div className="text-xs text-gray-500">{c.phone}</div>
                </div>
              </button>
            ))
          )}
        </div>
        <div className="border-t px-4 py-3 text-right">
          <button onClick={onClose} className="rounded-md px-3 py-1.5 text-sm hover:bg-gray-100">Cancel</button>
        </div>
      </div>
    </div>
  );
}
