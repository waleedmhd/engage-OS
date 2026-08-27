'use client';

import { useState } from 'react';
import { Play, Pause } from 'lucide-react';
import type { MediaAssetBrief } from '@/types/api';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? '';

function mediaUrl(assetId: string): string {
  return `${API_BASE}/media/${assetId}/file`;
}

export function MediaRenderer({
  mediaType,
  media,
}: {
  mediaType: string;
  media: MediaAssetBrief[];
}) {
  if (!media.length) return null;

  const asset = media[0];

  switch (mediaType) {
    case 'image':
      return <ImageBubble asset={asset} />;
    case 'video':
      return <VideoBubble asset={asset} />;
    case 'audio':
      return <AudioBubble asset={asset} />;
    default:
      return null;
  }
}

function ImageBubble({ asset }: { asset: MediaAssetBrief }) {
  const [open, setOpen] = useState(false);
  const url = mediaUrl(asset.id);

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="block w-full cursor-pointer"
      >
        <img
          src={url}
          alt=""
          className="max-h-64 w-full object-cover"
          loading="lazy"
        />
      </button>
      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80"
          onClick={() => setOpen(false)}
        >
          <img
            src={url}
            alt=""
            className="max-h-[90vh] max-w-[90vw] object-contain"
          />
        </div>
      )}
    </>
  );
}

function VideoBubble({ asset }: { asset: MediaAssetBrief }) {
  const url = mediaUrl(asset.id);
  return (
    <div className="max-h-64 w-full">
      <video
        src={url}
        controls
        preload="metadata"
        className="max-h-64 w-full object-cover"
      >
        Your browser does not support video playback.
      </video>
    </div>
  );
}

function AudioBubble({ asset }: { asset: MediaAssetBrief }) {
  const url = mediaUrl(asset.id);
  const [playing, setPlaying] = useState(false);
  const [audio, setAudio] = useState<HTMLAudioElement | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  function togglePlay() {
    if (!audio) {
      const a = new Audio(url);
      a.addEventListener('timeupdate', () => setCurrentTime(a.currentTime));
      a.addEventListener('loadedmetadata', () => setDuration(a.duration));
      a.addEventListener('ended', () => {
        setPlaying(false);
        setCurrentTime(0);
      });
      a.play();
      setPlaying(true);
      setAudio(a);
    } else if (playing) {
      audio.pause();
      setPlaying(false);
    } else {
      audio.play();
      setPlaying(true);
    }
  }

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0;

  return (
    <div className="flex items-center gap-3 px-3 py-2.5 min-w-[180px]">
      <button
        onClick={togglePlay}
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground"
      >
        {playing ? (
          <Pause className="h-4 w-4" />
        ) : (
          <Play className="h-4 w-4" />
        )}
      </button>
      <div className="flex-1 min-w-0">
        <div className="h-1.5 w-full rounded-full bg-gray-200">
          <div
            className="h-1.5 rounded-full bg-primary transition-all"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>
      <span className="text-xs text-gray-500 shrink-0">
        {asset.duration_seconds
          ? fmtDuration(asset.duration_seconds)
          : duration > 0
          ? fmtDuration(duration)
          : ''}
      </span>
    </div>
  );
}

function fmtDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}
