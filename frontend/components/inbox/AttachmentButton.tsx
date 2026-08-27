'use client';

import { useRef } from 'react';
import { Paperclip, Image, Video } from 'lucide-react';

export function AttachmentButton({
  onSelected,
  disabled,
}: {
  onSelected: (file: File) => void;
  disabled?: boolean;
}) {
  const fileRef = useRef<HTMLInputElement>(null);

  return (
    <>
      <input
        ref={fileRef}
        type="file"
        accept="image/*,video/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onSelected(file);
          if (fileRef.current) fileRef.current.value = '';
        }}
      />
      <button
        type="button"
        disabled={disabled}
        onClick={() => fileRef.current?.click()}
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-gray-500 hover:bg-gray-100 disabled:opacity-40"
        title="Attach image or video"
      >
        <Paperclip className="h-5 w-5" />
      </button>
    </>
  );
}
