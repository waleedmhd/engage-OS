'use client';

import { useEffect, useRef } from 'react';
import { createWsClient } from '@/lib/ws';
import { getAccessToken } from '@/lib/auth';

/**
 * Subscribe to the backend live-event WebSocket and react to events (P2.1).
 *
 * The socket authenticates with the stored JWT via `?token=`. The backend
 * relays inbox-relevant domain events; treat any received frame as a
 * "something changed, re-fetch" signal.
 */
export function useLiveEvents<T = unknown>(path: string, onEvent: (event: T) => void) {
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    const client = createWsClient({ path, getToken: getAccessToken });
    const unsubscribe = client.onMessage((data) => handlerRef.current(data as T));
    client.connect();
    return () => {
      unsubscribe();
      client.disconnect();
    };
  }, [path]);
}
