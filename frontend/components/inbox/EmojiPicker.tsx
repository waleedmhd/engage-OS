'use client';

import { useEffect, useRef, useState } from 'react';

const EMOJI_CATEGORIES: { label: string; emojis: string[] }[] = [
  {
    label: 'Smileys',
    emojis: [
      '😀', '😃', '😄', '😁', '😅', '😂', '🤣', '😊', '😇', '🙂', '😉', '😌', '😍', '🥰', '😘', '😗',
      '😋', '😛', '😜', '🤪', '😝', '🤑', '🤗', '🤭', '🤫', '🤔', '🤐', '🤨', '😐', '😑', '😶', '😏',
      '😒', '🙄', '😬', '😮', '😯', '😲', '😳', '🥺', '😢', '😭', '😤', '😠', '😡', '🤬', '😈', '👿',
      '💀', '☠️', '💩', '🤡', '👻', '👽', '🤖', '😺', '😸', '😹', '😻', '😼', '😽', '🙀', '😿', '😾',
    ],
  },
  {
    label: 'Gestures',
    emojis: [
      '👋', '🤚', '🖐️', '✋', '🖖', '👌', '🤌', '🤏', '✌️', '🤞', '🤟', '🤘', '🤙', '👈', '👉', '👆',
      '👇', '☝️', '👍', '👎', '✊', '👊', '🤛', '🤜', '👏', '🙌', '🤝', '🙏', '💪', '✍️', '🦵', '🦶',
    ],
  },
  {
    label: 'People',
    emojis: [
      '👶', '👧', '🧒', '👦', '👩', '🧑', '👨', '👩‍🦰', '👨‍🦰', '👱‍♀️', '👱‍♂️', '👩‍🦳', '👨‍🦳', '👩‍🦲', '👨‍🦲', '🧔',
      '👵', '🧓', '👴', '👲', '👳‍♀️', '👳‍♂️', '🧕', '👮‍♀️', '👮‍♂️', '👷‍♀️', '👷‍♂️', '💂‍♀️', '💂‍♂️', '🕵️‍♀️', '🕵️‍♂️', '👩‍⚕️',
    ],
  },
  {
    label: 'Animals',
    emojis: [
      '🐶', '🐱', '🐭', '🐹', '🐰', '🦊', '🐻', '🐼', '🐨', '🐯', '🦁', '🐮', '🐷', '🐸', '🐵', '🐔',
      '🐧', '🐦', '🐤', '🦆', '🦅', '🦉', '🦇', '🐺', '🐗', '🐴', '🦄', '🐝', '🐛', '🦋', '🐌', '🐞',
    ],
  },
  {
    label: 'Food',
    emojis: [
      '🍏', '🍎', '🍐', '🍊', '🍋', '🍌', '🍉', '🍇', '🍓', '🫐', '🍈', '🍒', '🍑', '🥭', '🍍', '🥥',
      '🥝', '🍅', '🍆', '🥑', '🥒', '🌶️', '🫑', '🌽', '🥕', '🧄', '🧅', '🥔', '🍞', '🥐', '🥖', '🧀',
      '🍔', '🍟', '🍕', '🌭', '🥪', '🌮', '🌯', '🥗', '🍝', '🍜', '🍣', '🍤', '🍚', '🍙', '🍘', '🍥',
      '🥩', '🍗', '🍖', '🥓', '🍳', '🥚', '🍿', '🧈', '🎂', '🍰', '🧁', '🍪', '🍩', '🍫', '🍬', '🍭',
    ],
  },
  {
    label: 'Activity',
    emojis: [
      '⚽', '🏀', '🏈', '⚾', '🥎', '🎾', '🏐', '🏉', '🥏', '🎱', '🪀', '🏓', '🏸', '🏒', '🏑', '🥍',
      '🏏', '🎿', '⛷️', '🏂', '🪂', '🏋️', '🤼', '🤸', '⛹️', '🤺', '🤾', '🏌️', '🏇', '🧘', '🏄', '🏊',
      '🚴', '🚵', '🏎️', '🏍️', '🎯', '🎮', '🎲', '🎰', '🧩', '♟️', '🎭', '🎨', '🎤', '🎧', '🎼', '🎹',
    ],
  },
  {
    label: 'Travel',
    emojis: [
      '🚗', '🚕', '🚙', '🚌', '🚎', '🏎️', '🚓', '🚑', '🚒', '🚐', '🛻', '🚚', '🚛', '🚜', '🏍️', '🛵',
      '🚲', '🛴', '✈️', '🛩️', '🚀', '🛸', '🚁', '⛵', '🚤', '🛳️', '⛴️', '🚢', '🚂', '🚆', '🚇', '🚊',
      '🚉', '🚏', '🚥', '🚦', '🏠', '🏡', '🏢', '🏣', '🏤', '🏥', '🏦', '🏨', '🏩', '🏪', '🏫', '🏬',
      '🗺️', '🌍', '🌎', '🌏', '🏔️', '⛰️', '🌋', '🗻', '🏕️', '🏖️', '🏜️', '🏝️', '🏞️', '🌅', '🌄', '🗽',
    ],
  },
  {
    label: 'Objects',
    emojis: [
      '💼', '📁', '📂', '📝', '📌', '📎', '✂️', '📏', '📐', '🔒', '🔓', '🔑', '🗝️', '🛠️', '🗡️', '⚔️',
      '🔧', '🔨', '⚒️', '🛡️', '🔫', '🏹', '⚙️', '🔗', '⛓️', '💰', '💵', '💴', '💶', '💷', '💳', '💎',
      '⚖️', '📦', '📫', '📪', '📭', '📬', '📧', '📨', '📩', '📤', '📥', '🗳️', '📜', '📃', '📄', '📑',
      '📊', '📈', '📉', '📇', '🗂️', '🗄️', '🗑️', '📅', '📆', '📋', '📎', '🖇️', '🖊️', '🖋️', '✒️', '🖌️',
      '🖍️', '📝', '✏️', '🔍', '🔎', '🔭', '🔬', '📡', '🕯️', '💡', '🔦', '🧨', '💣', '💊', '💉', '🩸',
    ],
  },
  {
    label: 'Symbols',
    emojis: [
      '❤️', '🧡', '💛', '💚', '💙', '💜', '🖤', '🤍', '🤎', '💔', '💕', '💖', '💗', '💘', '💝', '💟',
      '☮️', '✝️', '☪️', '🕉️', '☸️', '✡️', '🔯', '🕎', '☯️', '☦️', '🛐', '⛎', '♈', '♉', '♊', '♋',
      '♌', '♍', '♎', '♏', '♐', '♑', '♒', '♓', '⚛️', '🆔', '🚮', '🚰', '♿', '🚹', '🚺', '🚻',
      '🚼', '🚾', '🛂', '🛃', '🛄', '🛅', '⚠️', '🚸', '⛔', '🚫', '🚳', '🚭', '🚯', '🚱', '🚷', '📵',
      '🔞', '☢️', '☣️', '⬆️', '↗️', '➡️', '↘️', '⬇️', '↙️', '⬅️', '↖️', '↕️', '↔️', '↩️', '↪️', '⤴️',
      '⤵️', '🔃', '🔄', '🔙', '🔚', '🔛', '🔜', '🔝', '🛑', '⏹️', '⏺️', '⏏️', '✅', '❌', '❓', '❗',
    ],
  },
];

const RECENT_KEY = 'emoji_recent';

function loadRecent(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveRecent(emoji: string) {
  const recents = loadRecent().filter((e) => e !== emoji);
  recents.unshift(emoji);
  localStorage.setItem(RECENT_KEY, JSON.stringify(recents.slice(0, 24)));
}

export function EmojiPicker({
  onSelect,
  onClose,
}: {
  onSelect: (emoji: string) => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState(0);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [onClose]);

  const recents = loadRecent();
  const categories = recents.length > 0
    ? [{ label: 'Recent', emojis: recents }, ...EMOJI_CATEGORIES]
    : EMOJI_CATEGORIES;

  const visible = categories[tab]?.emojis ?? [];

  return (
    <div
      ref={ref}
      className="absolute bottom-full left-0 mb-2 w-80 rounded-lg border bg-white shadow-xl z-50"
    >
      {/* Category tabs */}
      <div className="flex overflow-x-auto border-b px-1 py-1">
        {categories.map((cat, i) => (
          <button
            key={cat.label}
            onClick={() => setTab(i)}
            className={`shrink-0 px-2.5 py-1.5 text-xs rounded ${
              i === tab
                ? 'bg-gray-100 font-medium text-gray-900'
                : 'text-gray-500 hover:bg-gray-50'
            }`}
          >
            {i === 0 && recents.length > 0 ? '🕐' : cat.emojis[0]}
          </button>
        ))}
      </div>
      {/* Emoji grid */}
      <div className="grid grid-cols-8 gap-0.5 p-2 max-h-[240px] overflow-y-auto">
        {visible.map((emoji, i) => (
          <button
            key={`${emoji}-${i}`}
            onClick={() => {
              saveRecent(emoji);
              onSelect(emoji);
            }}
            className="flex h-9 w-9 items-center justify-center rounded text-xl hover:bg-gray-100"
          >
            {emoji}
          </button>
        ))}
      </div>
    </div>
  );
}
