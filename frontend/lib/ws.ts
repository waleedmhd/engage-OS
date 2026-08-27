/**
 * Browser WebSocket client factory with reconnect-with-backoff.
 *
 * Used by `useLiveEvents`. Backend `/ws/inbox` relays inbox-relevant domain
 * events (P2.1); pass `token` so the socket authenticates via `?token=`.
 */

import { env } from '@/lib/env';

export type WsClient = {
  connect: () => void;
  disconnect: () => void;
  send: (data: unknown) => void;
  onMessage: (handler: (data: unknown) => void) => () => void;
};

type ClientOptions = {
  path: string;
  token?: string | null;
  /** Callback that returns a fresh JWT on each reconnect. Prefer this over
   *  `token` so the WebSocket doesn't reuse an expired token. */
  getToken?: () => string | null | undefined;
  maxBackoffMs?: number;
};

export function createWsClient(opts: ClientOptions): WsClient {
  const baseDelay = 500;
  const maxDelay = opts.maxBackoffMs ?? 15_000;

  const handlers = new Set<(data: unknown) => void>();
  let socket: WebSocket | null = null;
  let attempt = 0;
  let stopped = false;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  const scheduleReconnect = () => {
    if (stopped) return;
    const delay = Math.min(maxDelay, baseDelay * 2 ** attempt);
    attempt += 1;
    reconnectTimer = setTimeout(open, delay);
  };

  const buildUrl = () => {
    const base = env.wsUrl.replace(/\/$/, '');
    const path = opts.path.startsWith('/') ? opts.path : `/${opts.path}`;
    // Backend `/ws/inbox` authenticates via the `?token=` query param
    // (the HTTP Bearer/cookie dependency does not run for WebSockets).
    const token = opts.getToken ? opts.getToken() : opts.token;
    const qs = token ? `?token=${encodeURIComponent(token)}` : '';
    return `${base}${path}${qs}`;
  };

  const open = () => {
    if (typeof window === 'undefined') return;
    socket = new WebSocket(buildUrl());

    socket.addEventListener('open', () => {
      attempt = 0;
    });

    socket.addEventListener('message', (event) => {
      let data: unknown = event.data;
      try {
        data = JSON.parse(event.data as string);
      } catch {
        // leave as raw string
      }
      handlers.forEach((h) => h(data));
    });

    socket.addEventListener('close', () => {
      socket = null;
      scheduleReconnect();
    });

    socket.addEventListener('error', () => {
      socket?.close();
    });
  };

  return {
    connect() {
      stopped = false;
      open();
    },
    disconnect() {
      stopped = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
      socket = null;
    },
    send(data: unknown) {
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(typeof data === 'string' ? data : JSON.stringify(data));
      }
    },
    onMessage(handler) {
      handlers.add(handler);
      return () => handlers.delete(handler);
    },
  };
}
