'use client';

import { useCallback, useEffect, useState } from 'react';
import { Bell, Menu } from 'lucide-react';
import { usePathname, useRouter } from 'next/navigation';
import clsx from 'clsx';
import { Brand } from './Brand';
import { NAV_GROUPS } from './Sidebar';
import { authedFetch } from '@/lib/authedFetch';
import { useLiveEvents } from '@/hooks/useLiveEvents';
import type { NeedsHumanCountResponse } from '@/types/api';

type TopbarProps = {
  onMenuClick?: () => void;
};

export function Topbar({ onMenuClick }: TopbarProps) {
  const pathname = usePathname();
  const router = useRouter();

  const activeGroup = NAV_GROUPS.find((group) =>
    group.items.some(
      ({ href }) => pathname === href || pathname?.startsWith(`${href}/`),
    ),
  );

  const [needsHuman, setNeedsHuman] = useState<NeedsHumanCountResponse | null>(null);

  const fetchNeedsHuman = useCallback(async () => {
    try {
      const data = await authedFetch<NeedsHumanCountResponse>(
        '/conversations/needs-human-count',
      );
      setNeedsHuman(data);
    } catch {
      // Silently ignore — notification is best-effort.
    }
  }, []);

  useEffect(() => {
    fetchNeedsHuman();
  }, [fetchNeedsHuman]);

  useLiveEvents<{ event?: string }>(
    '/inbox',
    () => fetchNeedsHuman(),
  );

  const count = needsHuman?.total ?? 0;

  return (
    <div>
      {activeGroup && (
        <div className={clsx('h-[3px] w-full', activeGroup.color)} />
      )}
      <header className="flex h-14 items-center justify-between border-b bg-white px-4 sm:px-6">
        <div className="flex items-center gap-3">
          <button
            onClick={onMenuClick}
            className="-ml-1 rounded-md p-1 text-muted-foreground hover:bg-muted md:hidden"
            aria-label="Open menu"
          >
            <Menu className="h-5 w-5" />
          </button>
          <Brand variant="short" size={24} className="text-sm" />
        </div>

        <div className="flex items-center gap-3">
          {count > 0 && (
            <button
              onClick={() =>
                router.push('/inbox?state=AWAITING_APPROVAL,HUMAN_ASSIGNED')
              }
              className="relative flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 transition-colors"
              title={`${needsHuman?.awaiting_approval ?? 0} awaiting approval, ${needsHuman?.human_assigned ?? 0} assigned`}
            >
              <Bell className="h-4 w-4" />
              <span>{count}</span>
              <span className="hidden sm:inline text-red-600">need attention</span>
            </button>
          )}
        </div>
      </header>
    </div>
  );
}
