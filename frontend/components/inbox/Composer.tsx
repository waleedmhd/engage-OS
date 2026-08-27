'use client';

import { useState, useCallback, useRef } from 'react';
import { Send, Smile, X, Contact } from 'lucide-react';
import { Spinner } from '@/components/shared/ui';
import { authedFetch } from '@/lib/authedFetch';
import type { MessageResponse, MediaAssetBrief, ContactResponse } from '@/types/api';
import { AttachmentButton } from './AttachmentButton';
import { VoiceRecorder } from './VoiceRecorder';
import { EmojiPicker } from './EmojiPicker';
import { ContactShareDialog } from './ContactShareDialog';

export function Composer({
  conversationId,
  onMessageSent,
  replyTo,
  onCancelReply,
}: {
  conversationId: string;
  onMessageSent: (msg: MessageResponse) => void;
  replyTo?: { id: string; content: string; isOutbound: boolean } | null;
  onCancelReply?: () => void;
}) {
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [emojiOpen, setEmojiOpen] = useState(false);
  const [contactShareOpen, setContactShareOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const insertEmoji = useCallback((emoji: string) => {
    const el = textareaRef.current;
    if (el) {
      const start = el.selectionStart ?? text.length;
      const end = el.selectionEnd ?? text.length;
      setText(text.slice(0, start) + emoji + text.slice(end));
      // Restore cursor after the emoji
      setTimeout(() => {
        el.focus();
        el.setSelectionRange(start + emoji.length, start + emoji.length);
      }, 0);
    } else {
      setText((prev) => prev + emoji);
    }
    setEmojiOpen(false);
  }, [text]);

  const sendMessage = useCallback(
    async (content: string, opts?: { mediaAssetId?: string; contextId?: string; msgType?: string }) => {
      setSending(true);
      const optimistic: MessageResponse = {
        id: `optimistic-${Date.now()}`,
        conversation_id: conversationId,
        direction: 'OUTBOUND',
        sender_type: 'agent',
        content,
        delivery_status: 'QUEUED',
        msg_type: opts?.msgType || 'text',
        media: [],
        context_message_id: opts?.contextId ?? null,
        context_message: replyTo
          ? { id: replyTo.id, content: replyTo.content, msg_type: 'text' }
          : null,
      };
      onMessageSent(optimistic);

      try {
        const body: Record<string, unknown> = { conversation_id: conversationId, content };
        if (opts?.mediaAssetId) body.media_asset_id = opts.mediaAssetId;
        if (opts?.contextId) body.context_message_id = opts.contextId;
        if (opts?.msgType) body.msg_type = opts.msgType;

        const sent = await authedFetch<MessageResponse>('/messages/send', {
          method: 'POST',
          json: body,
        });
        onMessageSent(sent);
        return sent;
      } catch {
        return null;
      } finally {
        setSending(false);
      }
    },
    [conversationId, onMessageSent, replyTo],
  );

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!text.trim() || sending || uploading) return;
      const content = text.trim();
      setText('');
      const replyMsg = replyTo;
      if (onCancelReply) onCancelReply();
      sendMessage(content, { contextId: replyMsg?.id });
    },
    [text, sending, uploading, sendMessage, replyTo, onCancelReply],
  );

  const handleFile = useCallback(
    async (file: File) => {
      setUploading(true);
      try {
        const form = new FormData();
        form.append('file', file);
        const asset = await authedFetch<MediaAssetBrief>('/media/upload', {
          method: 'POST',
          body: form,
        });
        setText('');
        sendMessage(file.name, { mediaAssetId: asset.id });
      } finally {
        setUploading(false);
      }
    },
    [sendMessage],
  );

  const handleVoice = useCallback(
    async (blob: Blob, durationSec: number) => {
      setUploading(true);
      try {
        const form = new FormData();
        form.append('file', blob, `voice-${Date.now()}.webm`);
        const asset = await authedFetch<MediaAssetBrief>('/media/upload', {
          method: 'POST',
          body: form,
        });
        sendMessage(`[Voice note ${durationSec.toFixed(1)}s]`, { mediaAssetId: asset.id });
      } finally {
        setUploading(false);
      }
    },
    [sendMessage],
  );

  const handleShareContact = useCallback(
    (contact: ContactResponse) => {
      const phone = contact.phone;
      const name = contact.name || phone;
      const content = `${name} — ${phone}`;
      sendMessage(content, { msgType: 'contact' });
    },
    [sendMessage],
  );

  const busy = sending || uploading;

  return (
    <div className="border-t relative">
      {/* Reply preview */}
      {replyTo && (
        <div className="flex items-center gap-2 bg-[#e2f0fb] border-l-4 border-l-blue-400 px-3 py-2 text-xs">
          <div className="flex-1 min-w-0">
            <span className="font-medium text-blue-600">
              Replying to {replyTo.isOutbound ? 'yourself' : 'contact'}
            </span>
            <div className="text-gray-600 truncate">{replyTo.content}</div>
          </div>
          <button
            onClick={onCancelReply}
            className="shrink-0 p-1 rounded hover:bg-black/10"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {/* Emoji picker */}
      {emojiOpen && (
        <EmojiPicker
          onSelect={insertEmoji}
          onClose={() => setEmojiOpen(false)}
        />
      )}

      {/* Contact share dialog */}
      <ContactShareDialog
        open={contactShareOpen}
        onClose={() => setContactShareOpen(false)}
        onSelect={handleShareContact}
      />

      <form onSubmit={handleSubmit} className="flex items-end gap-2 p-3">
        {/* Emoji button */}
        <button
          type="button"
          onClick={() => setEmojiOpen((v) => !v)}
          disabled={busy}
          className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-gray-500 hover:bg-gray-100 disabled:opacity-40"
          title="Emoji"
        >
          <Smile className="h-5 w-5" />
        </button>

        <AttachmentButton onSelected={handleFile} disabled={busy} />

        {/* Share contact button */}
        <button
          type="button"
          onClick={() => setContactShareOpen(true)}
          disabled={busy}
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-gray-500 hover:bg-gray-100 disabled:opacity-40"
          title="Share contact"
        >
          <Contact className="h-5 w-5" />
        </button>

        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={1}
          placeholder="Type a message…"
          className="flex-1 resize-none rounded-2xl border px-4 py-2.5 text-sm outline-none focus:border-primary"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              handleSubmit(e as unknown as React.FormEvent);
            }
          }}
          style={{ minHeight: '2.5rem' }}
        />

        {text.trim() ? (
          <button
            type="submit"
            disabled={busy}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground disabled:opacity-50"
          >
            {sending ? (
              <Spinner className="text-primary-foreground h-4 w-4" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </button>
        ) : (
          <VoiceRecorder onRecorded={handleVoice} disabled={busy} />
        )}
      </form>
    </div>
  );
}
