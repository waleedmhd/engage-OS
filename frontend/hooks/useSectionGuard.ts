'use client';

import { useAuth } from '@/hooks/useAuth';

/**
 * Defense-in-depth guard for pages behind section-access control.
 * Returns true if the user is an admin or has the given section key
 * in their accessible_sections list.
 */
export function useSectionGuard(sectionKey: string): {
  allowed: boolean;
  isLoading: boolean;
} {
  const { user, isLoading } = useAuth();

  if (isLoading) return { allowed: false, isLoading: true };
  if (!user) return { allowed: false, isLoading: false };

  // Admin sees everything.
  if (user.role === 'admin') return { allowed: true, isLoading: false };

  // Agent — check explicit grants.
  return {
    allowed: user.accessible_sections.includes(sectionKey),
    isLoading: false,
  };
}
