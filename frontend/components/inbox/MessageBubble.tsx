'use client';

import { useState } from 'react';
import { Check, CheckCheck, Clock, Reply, Forward, Copy, Trash2, List, X as XIcon, Contact } from 'lucide-react';
import type { MessageResponse } from '@/types/api';
import { MediaRenderer } from './MediaRenderer';

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

function DeliveryIcon({ status, lastError }: { status: string; lastError?: string | null }) {
  const cls = 'h-3.5 w-3.5';
  switch (status.toUpperCase()) {
    case 'SENT':
      return <Check className={cls} />;
    case 'DELIVERED':
      return <CheckCheck className={cls} />;
    case 'READ':
      return <CheckCheck className={`${cls} text-sky-500`} />;
    case 'FAILED':
      return (
        <span title={lastError || 'Delivery failed'}>
          <XIcon className={`${cls} text-red-500`} />
        </span>
      );
    default:
      return <Clock className={cls} />;
  }
}

export function MessageBubble({
  message,
  onReply,
  onForward,
  onDelete,
  onSelect,
  selectionMode,
  selected,
  onToggleSelect,
}: {
  message: MessageResponse;
  onReply?: (msg: MessageResponse) => void;
  onForward?: (msg: MessageResponse) => void;
  onDelete?: (msg: MessageResponse) => void;
  onSelect?: (msg: MessageResponse) => void;
  selectionMode?: boolean;
  selected?: boolean;
  onToggleSelect?: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  const outbound = String(message.direction).toUpperCase() === 'OUTBOUND';
  const isText = message.msg_type === 'text';
  const isContact = message.msg_type === 'contact';
  const hasMedia = message.media && message.media.length > 0;
  const hasContext = !!message.context_message;
  const isReaction =
    isText &&
    hasContext &&
    message.content.length <= 8 &&
    /^[\p{Emoji}‍️]+$/u.test(message.content.trim());

  return (
    <div
      className={`flex ${outbound ? 'justify-end' : 'justify-start'} relative group`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Selection checkbox */}
      {selectionMode && (
        <div
          className={`shrink-0 w-8 h-8 rounded-full border-2 mr-2 self-center flex items-center justify-center cursor-pointer ${
            selected ? 'bg-blue-600 border-blue-600 text-white' : 'border-gray-300'
          }`}
          onClick={onToggleSelect}
        >
          {selected && <span className="text-sm">✓</span>}
        </div>
      )}

      <div className="relative">
        {/* Action bar — appears on hover (outside selection mode) */}
        {hovered && !selectionMode && (
          <div
            className={`absolute top-full -mt-1 ${
              outbound ? 'right-0' : 'left-0'
            } flex gap-1 bg-white rounded-full border shadow px-1.5 py-0.5 z-10`}
          >
            {onReply && (
              <button
                onClick={(e) => { e.stopPropagation(); onReply(message); }}
                className="p-1 rounded-full hover:bg-gray-100"
                title="Reply"
              >
                <Reply className="h-3.5 w-3.5 text-gray-500" />
              </button>
            )}
            {onForward && (
              <button
                onClick={(e) => { e.stopPropagation(); onForward(message); }}
                className="p-1 rounded-full hover:bg-gray-100"
                title="Forward"
              >
                <Forward className="h-3.5 w-3.5 text-gray-500" />
              </button>
            )}
            <button
              onClick={(e) => {
                e.stopPropagation();
                navigator.clipboard.writeText(message.content).catch(() => {});
              }}
              className="p-1 rounded-full hover:bg-gray-100"
              title="Copy"
            >
              <Copy className="h-3.5 w-3.5 text-gray-500" />
            </button>
            {onDelete && (
              <button
                onClick={(e) => { e.stopPropagation(); onDelete(message); }}
                className="p-1 rounded-full hover:bg-red-100"
                title="Delete"
              >
                <Trash2 className="h-3.5 w-3.5 text-gray-500" />
              </button>
            )}
            {onSelect && (
              <button
                onClick={(e) => { e.stopPropagation(); onSelect(message); }}
                className="p-1 rounded-full hover:bg-gray-100"
                title="Select messages"
              >
                <List className="h-3.5 w-3.5 text-gray-500" />
              </button>
            )}
          </div>
        )}

        {/* Long-press/right-click for selection mode */}
        <div
          onContextMenu={(e) => {
            if (!selectionMode && onToggleSelect) {
              e.preventDefault();
              onToggleSelect();
            }
          }}
          className={`max-w-[75%] overflow-hidden shadow-sm ${
            isReaction
              ? 'rounded-xl bg-gray-50 border border-gray-100'
              : outbound
                ? 'rounded-2xl rounded-br-sm bg-[#d9fdd3]'
                : 'rounded-2xl rounded-bl-sm bg-white'
          } ${selected ? 'ring-2 ring-blue-400' : ''}`}
        >
          {/* Quoted context (reply/forward preview) */}
          {hasContext && (
            <div className="bg-black/5 border-l-[3px] border-l-blue-400 px-3 py-1.5 text-xs text-gray-600">
              <span className="font-medium text-blue-500">
                {outbound ? 'You' : 'Contact'}
              </span>
              <div className="truncate max-w-full">
                {message.context_message?.content ?? ''}
              </div>
            </div>
          )}

          {/* Media content */}
          {hasMedia && (
            <MediaRenderer
              mediaType={message.msg_type}
              media={message.media}
            />
          )}

          {/* Contact card rendering */}
          {isContact && (
            <div className="flex items-center gap-3 px-3 py-2.5">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-blue-100">
                <Contact className="h-5 w-5 text-blue-600" />
              </div>
              <div className="min-w-0">
                <div className="text-sm font-medium text-gray-900 truncate">
                  {message.content.split(' — ')[0] || message.content}
                </div>
                <div className="text-xs text-gray-500">
                  {message.content.split(' — ')[1] || ''}
                </div>
              </div>
            </div>
          )}

          {/* Reaction: compact emoji bubble */}
          {isReaction && (
            <div className="flex items-center gap-2 px-2.5 py-1.5">
              <span className="text-xl leading-none">{message.content}</span>
              <span className="text-[10px] text-gray-400">reacted</span>
            </div>
          )}

          {/* Text content */}
          {isText && !isReaction && (
            <p className="whitespace-pre-wrap px-3 py-2 text-sm text-gray-900">
              {message.content}
            </p>
          )}
          {!isText && !isContact && !isReaction && message.content && !message.content.startsWith('[') && (
            <p className="whitespace-pre-wrap px-3 py-1.5 text-sm text-gray-700">
              {message.content}
            </p>
          )}

          {/* Timestamp + delivery */}
          <div className="flex items-center justify-end gap-1 px-3 pb-1.5 text-[10px] text-gray-500">
            <span>{fmtTime(message.created_at)}</span>
            {outbound && <DeliveryIcon status={String(message.delivery_status)} lastError={message.last_error} />}
          </div>
        </div>
      </div>
    </div>
  );
}
