'use client';

import {
  ArrowDownToLine,
  ArrowUpFromLine,
  BarChart3,
  BookOpen,
  ChevronDown,
  ClipboardCheck,
  ClipboardList,
  FileText,
  HelpCircle,
  Inbox,
  Landmark,
  LogOut,
  Megaphone,
  MessageSquare,
  Package,
  PackageCheck,
  ScrollText,
  Settings,
  ShoppingCart,
  Tags,
  Truck,
  UserCog,
  Users,
  Warehouse,
} from 'lucide-react';
import { useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import clsx from 'clsx';
import { clearTokens } from '@/lib/auth';
import { clearAuthCache } from '@/hooks/useAuth';
import { Brand } from './Brand';

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

type NavGroup = {
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  color: string; // Tailwind bg class for the color dot
  items: NavItem[];
};

export const NAV_GROUPS: NavGroup[] = [
  {
    label: 'CRM',
    icon: Users,
    color: 'bg-blue-500',
    items: [
      { href: '/inbox', label: 'Inbox', icon: Inbox },
      { href: '/market', label: 'Market', icon: ShoppingCart },
      { href: '/market/messages', label: 'Messages', icon: MessageSquare },
      { href: '/market/review', label: 'Review Queue', icon: ClipboardCheck },
      { href: '/contacts', label: 'Contacts', icon: Users },
      { href: '/campaigns', label: 'Campaigns', icon: Megaphone },
      { href: '/templates', label: 'Templates', icon: ClipboardList },
      { href: '/tag-review', label: 'Tag Review', icon: Tags },
    ],
  },
  {
    label: 'Finance & Inventory',
    icon: Landmark,
    color: 'bg-green-500',
    items: [
      { href: '/finance/accounts', label: 'Accounts', icon: Landmark },
      { href: '/finance/journals', label: 'Journals', icon: BookOpen },
      { href: '/finance/receivables', label: 'Receivables', icon: ArrowDownToLine },
      { href: '/finance/payables', label: 'Payables', icon: ArrowUpFromLine },
      { href: '/inventory/items', label: 'Items', icon: Package },
      { href: '/inventory/stock', label: 'Stock', icon: Warehouse },
      { href: '/inventory/procurement', label: 'Procurement', icon: Truck },
      { href: '/inventory/fulfilment', label: 'Fulfilment', icon: PackageCheck },
      { href: '/reports', label: 'Reports', icon: FileText },
    ],
  },
  {
    label: 'Admin',
    icon: Settings,
    color: 'bg-red-500',
    items: [
      { href: '/analytics', label: 'Analytics', icon: BarChart3 },
      { href: '/settings', label: 'Settings', icon: Settings },
      { href: '/settings/tags', label: 'Tags', icon: Tags },
      { href: '/settings/campaign-categories', label: 'Campaign Categories', icon: Megaphone },
      { href: '/users', label: 'Users', icon: UserCog },
      { href: '/audit-logs', label: 'Audit Logs', icon: ScrollText },
    ],
  },
];

type SidebarProps = {
  mobileOpen?: boolean;
  onClose?: () => void;
  accessibleSections?: string[];
};

export function Sidebar({
  mobileOpen = false,
  onClose,
  accessibleSections,
}: SidebarProps) {

  const filteredGroups = accessibleSections
    ? NAV_GROUPS
        .map((group) => ({
          ...group,
          items: group.items.filter(
            (item) => accessibleSections.includes(item.href.slice(1)),
          ),
        }))
        .filter((group) => group.items.length > 0)
    : NAV_GROUPS;
  const pathname = usePathname();
  const router = useRouter();

  // Flatten all items for active-route detection
  const allNavItems: NavItem[] = filteredGroups.flatMap((g) => g.items);

  const activeHref = allNavItems
    .filter(
      ({ href }) => pathname === href || pathname?.startsWith(`${href}/`),
    )
    .sort((a, b) => b.href.length - a.href.length)[0]?.href;

  const activeGroupLabel = filteredGroups.find((group) =>
    group.items.some((item) => item.href === activeHref),
  )?.label;

  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => {
    const collapsed = new Set<string>();
    for (const group of filteredGroups) {
      if (group.label !== activeGroupLabel) {
        collapsed.add(group.label);
      }
    }
    return collapsed;
  });

  const toggleGroup = (label: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(label)) {
        next.delete(label);
      } else {
        next.add(label);
      }
      return next;
    });
  };

  const handleSignOut = () => {
    onClose?.();
    clearTokens();
    clearAuthCache();
    router.push('/login');
  };

  const helpActive = pathname === '/help';

  return (
    <>
      {/* Mobile overlay */}
      {mobileOpen ? (
        <div
          className="fixed inset-0 z-40 bg-black/30 md:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      ) : null}

      <aside
        className={clsx(
          'fixed inset-y-0 left-0 z-50 flex h-screen w-60 flex-col border-r bg-white transition-transform duration-200 md:static md:z-auto md:translate-x-0',
          mobileOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <Brand variant="short" className="px-6 py-5 text-base" />
        <nav className="flex-1 overflow-y-auto px-2">
          <ul className="space-y-1">
            {filteredGroups.map((group) => {
              const isCollapsed = collapsedGroups.has(group.label);
              const GroupIcon = group.icon;
              return (
                <li key={group.label}>
                  <button
                    type="button"
                    onClick={() => toggleGroup(group.label)}
                    className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
                  >
                    <ChevronDown
                      className={clsx(
                        'h-3 w-3 transition-transform',
                        isCollapsed && '-rotate-90',
                      )}
                    />
                    <GroupIcon className="h-3.5 w-3.5" />
                    {group.label}
                    <span className={clsx('ml-auto h-2 w-2 shrink-0 rounded-full', group.color)} />
                  </button>
                  {!isCollapsed && (
                    <ul className="mt-0.5 space-y-1">
                      {group.items.map(({ href, label, icon: Icon }) => {
                        const active = href === activeHref;
                        return (
                          <li key={href}>
                            <Link
                              href={href}
                              onClick={onClose}
                              className={clsx(
                                'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                                active
                                  ? 'bg-accent text-accent-foreground'
                                  : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
                              )}
                            >
                              <Icon className="h-4 w-4" />
                              {label}
                            </Link>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="border-t px-2 py-3">
          <button
            type="button"
            onClick={handleSignOut}
            className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
          >
            <LogOut className="h-4 w-4" />
            Sign out
          </button>
          <Link
            href="/help"
            onClick={onClose}
            className={clsx(
              'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
              helpActive
                ? 'bg-accent text-accent-foreground'
                : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
            )}
          >
            <HelpCircle className="h-4 w-4" />
            Help &amp; Guide
          </Link>
          <p className="px-3 pt-2 text-xs text-muted-foreground">v0.1.0 · Powered by EngageOS</p>
        </div>
      </aside>
    </>
  );
}
