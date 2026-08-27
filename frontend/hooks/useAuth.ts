'use client';

import { useEffect, useState } from 'react';
import { authedFetch } from '@/lib/authedFetch';
import type { AuthUser } from '@/types/api';

let cachedUser: AuthUser | null = null;
let inflight: Promise<AuthUser | null> | null = null;

async function loadUser(): Promise<AuthUser | null> {
  if (cachedUser) return cachedUser;
  if (!inflight) {
    inflight = authedFetch<AuthUser>('/auth/me')
      .then((u) => {
        cachedUser = u;
        return u;
      })
      .catch(() => null)
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

export function clearAuthCache(): void {
  cachedUser = null;
  inflight = null;
}

export function useAuth(): { user: AuthUser | null; isLoading: boolean } {
  const [user, setUser] = useState<AuthUser | null>(cachedUser);
  const [isLoading, setIsLoading] = useState(!cachedUser);

  useEffect(() => {
    let active = true;
    if (cachedUser) {
      setUser(cachedUser);
      setIsLoading(false);
      return;
    }
    loadUser().then((u) => {
      if (!active) return;
      setUser(u);
      setIsLoading(false);
    });
    return () => {
      active = false;
    };
  }, []);

  return { user, isLoading };
}
