'use client';

import { useState } from 'react';
import { Sidebar } from '@/components/shared/Sidebar';
import { Topbar } from '@/components/shared/Topbar';
import { useAuth } from '@/hooks/useAuth';

/**
 * Client shell that owns the mobile sidebar drawer state. The sidebar is an
 * off-canvas drawer below `md` (collapsed by default) and a static column at
 * `md`+ so the selected page fills the mobile screen.
 */
export function DashboardShell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const { user } = useAuth();

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <Sidebar
        mobileOpen={mobileOpen}
        onClose={() => setMobileOpen(false)}
        accessibleSections={user?.accessible_sections}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onMenuClick={() => setMobileOpen(true)} />
        <main className="flex-1 overflow-y-auto px-4 py-4 sm:px-8 sm:py-6">
          {children}
        </main>
      </div>
    </div>
  );
}
