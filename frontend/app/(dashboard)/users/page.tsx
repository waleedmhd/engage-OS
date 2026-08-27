'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Check, KeyRound, Pencil, Plus, X } from 'lucide-react';
import clsx from 'clsx';
import { PageHeader } from '@/components/shared/PageHeader';
import {
  ErrorBox,
  PermissionState,
  SkeletonRows,
  Spinner,
} from '@/components/shared/ui';
import { authedFetch } from '@/lib/authedFetch';
import { fetchPage } from '@/lib/lists';
import { useAuth } from '@/hooks/useAuth';
import type {
  PasswordResetRequest,
  UserCreateRequest,
  UserListItem,
  UserRoleWire,
  UserUpdateRequest,
  UsersListResponse,
} from '@/types/api';

type FetchError = Error & { status?: number; payload?: unknown };

const PAGE_SIZE = 50;

function formatServerError(err: unknown, fallback: string): string {
  const e = err as FetchError;
  const payload = e?.payload as
    | { detail?: unknown; error?: { message?: string }; message?: string }
    | undefined;
  if (payload?.detail) {
    if (typeof payload.detail === 'string') return payload.detail;
    if (Array.isArray(payload.detail)) {
      return payload.detail
        .map((d: { loc?: unknown[]; msg?: string }) => {
          const loc = Array.isArray(d.loc) ? d.loc.join('.') : '';
          return loc ? `${loc}: ${d.msg ?? ''}` : (d.msg ?? '');
        })
        .filter(Boolean)
        .join('; ');
    }
  }
  if (payload?.message) return payload.message;
  if (payload?.error?.message) return payload.error.message;
  return e?.message || fallback;
}

function friendlyError(err: unknown, fallback: string): string {
  const raw = formatServerError(err, fallback);
  if (raw.includes('cannot_modify_self'))
    return 'You cannot demote or deactivate your own account.';
  if (raw.includes('last_active_admin'))
    return 'Refused — this would leave the system with no active admin.';
  if (raw.includes('email_taken'))
    return 'A user with that email already exists.';
  if (raw.includes('no_changes')) return 'No fields were changed.';
  return raw;
}

export default function UsersPage() {
  const { user, isLoading: authLoading } = useAuth();
  const isAdmin = user?.role === 'admin';

  if (authLoading) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Users"
          description="Manage user accounts and roles."
        />
        <SkeletonRows rows={6} />
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Users"
          description="Manage user accounts and roles."
        />
        <PermissionState title="Admin only" />
      </div>
    );
  }

  return <UsersAdminView currentUserId={user?.id ?? ''} />;
}

type RoleFilter = 'all' | UserRoleWire;
type ActiveFilter = 'all' | 'active' | 'inactive';

function UsersAdminView({ currentUserId }: { currentUserId: string }) {
  const [data, setData] = useState<UsersListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [q, setQ] = useState('');
  const [qDebounced, setQDebounced] = useState('');
  const [role, setRole] = useState<RoleFilter>('all');
  const [active, setActive] = useState<ActiveFilter>('all');
  const [offset, setOffset] = useState(0);

  const [showCreate, setShowCreate] = useState(false);
  const [editTarget, setEditTarget] = useState<UserListItem | null>(null);

  // debounce search
  useEffect(() => {
    const id = setTimeout(() => setQDebounced(q), 300);
    return () => clearTimeout(id);
  }, [q]);

  const params = useMemo(() => {
    const sp = new URLSearchParams();
    if (role !== 'all') sp.set('role', role);
    if (active !== 'all') sp.set('is_active', active === 'active' ? 'true' : 'false');
    if (qDebounced) sp.set('q', qDebounced);
    sp.set('limit', String(PAGE_SIZE));
    sp.set('offset', String(offset));
    return sp.toString();
  }, [role, active, qDebounced, offset]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const body = await fetchPage<UserListItem>(`/users?${params}`);
      setData({ items: body.items, total: body.total, limit: PAGE_SIZE, offset });
    } catch (err) {
      setError(friendlyError(err, 'Failed to load users.'));
    } finally {
      setLoading(false);
    }
  }, [params, offset]);

  useEffect(() => {
    load();
  }, [load]);

  // reset paging on filter change
  useEffect(() => {
    setOffset(0);
  }, [role, active, qDebounced]);

  const total = data?.total ?? 0;
  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Users"
        description="Manage user accounts, roles, and access. Admin-only."
      />

      <section className="rounded-lg border bg-white">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b px-5 py-4">
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search email or name…"
              className="w-64 rounded-md border px-3 py-1.5 text-sm"
            />
            <PillGroup
              value={role}
              onChange={setRole}
              options={[
                { value: 'all', label: 'All roles' },
                { value: 'admin', label: 'Admin' },
                { value: 'agent', label: 'Agent' },
              ]}
            />
            <PillGroup
              value={active}
              onChange={setActive}
              options={[
                { value: 'all', label: 'All' },
                { value: 'active', label: 'Active' },
                { value: 'inactive', label: 'Inactive' },
              ]}
            />
          </div>
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground"
          >
            <Plus className="h-4 w-4" /> New user
          </button>
        </header>

        <div className="px-5 py-4">
          {error ? <ErrorBox message={error} onRetry={load} /> : null}
          {loading || !data ? (
            <SkeletonRows rows={6} />
          ) : data.items.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No users match these filters.
            </p>
          ) : (
            <UsersTable
              items={data.items}
              currentUserId={currentUserId}
              onEdit={setEditTarget}
            />
          )}
        </div>

        {data && total > PAGE_SIZE ? (
          <footer className="flex items-center justify-between border-t px-5 py-3 text-xs text-muted-foreground">
            <span>
              {total} user{total === 1 ? '' : 's'} · page {page} of {pageCount}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                className="rounded-md border px-3 py-1 disabled:opacity-40"
              >
                Prev
              </button>
              <button
                type="button"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset((o) => o + PAGE_SIZE)}
                className="rounded-md border px-3 py-1 disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </footer>
        ) : null}
      </section>

      {showCreate ? (
        <CreateUserModal
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false);
            load();
          }}
        />
      ) : null}

      {editTarget ? (
        <EditUserModal
          user={editTarget}
          currentUserId={currentUserId}
          onClose={() => setEditTarget(null)}
          onSaved={() => {
            setEditTarget(null);
            load();
          }}
        />
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Table
// ---------------------------------------------------------------------------

function UsersTable({
  items,
  currentUserId,
  onEdit,
}: {
  items: UserListItem[];
  currentUserId: string;
  onEdit: (u: UserListItem) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-xs uppercase text-muted-foreground">
          <tr className="border-b">
            <th className="px-2 py-2 text-left font-medium">Name</th>
            <th className="px-2 py-2 text-left font-medium">Email</th>
            <th className="px-2 py-2 text-left font-medium">Role</th>
            <th className="px-2 py-2 text-left font-medium">Status</th>
            <th className="px-2 py-2 text-left font-medium">Created</th>
            <th className="px-2 py-2" />
          </tr>
        </thead>
        <tbody>
          {items.map((u) => (
            <tr
              key={u.id}
              className="border-b last:border-b-0 hover:bg-accent/30"
            >
              <td className="px-2 py-2">
                {u.name ?? <span className="text-muted-foreground">—</span>}
                {u.id === currentUserId ? (
                  <span className="ml-2 rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-700">
                    you
                  </span>
                ) : null}
              </td>
              <td className="px-2 py-2">{u.email}</td>
              <td className="px-2 py-2">
                <RoleBadge role={u.role} />
              </td>
              <td className="px-2 py-2">
                <StatusBadge active={u.is_active} />
              </td>
              <td className="px-2 py-2 text-xs text-muted-foreground">
                {new Date(u.created_at).toLocaleDateString()}
              </td>
              <td className="px-2 py-2 text-right">
                <button
                  type="button"
                  onClick={() => onEdit(u)}
                  className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs hover:bg-accent"
                >
                  <Pencil className="h-3 w-3" /> Edit
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RoleBadge({ role }: { role: UserRoleWire }) {
  return (
    <span
      className={clsx(
        'inline-block rounded-full px-2 py-0.5 text-[11px] font-medium',
        role === 'admin'
          ? 'bg-purple-100 text-purple-700'
          : 'bg-gray-100 text-gray-700',
      )}
    >
      {role}
    </span>
  );
}

function StatusBadge({ active }: { active: boolean }) {
  return (
    <span
      className={clsx(
        'inline-block rounded-full px-2 py-0.5 text-[11px] font-medium',
        active ? 'bg-green-100 text-green-700' : 'bg-red-50 text-red-700',
      )}
    >
      {active ? 'Active' : 'Inactive'}
    </span>
  );
}

function PillGroup<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
}) {
  return (
    <div className="inline-flex rounded-md border bg-white text-xs">
      {options.map((opt, i) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={clsx(
            'px-2.5 py-1.5',
            i !== 0 && 'border-l',
            value === opt.value
              ? 'bg-accent font-medium'
              : 'text-muted-foreground hover:bg-accent/50',
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Modals
// ---------------------------------------------------------------------------

function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-lg bg-white shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b px-5 py-3">
          <h3 className="text-base font-semibold">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-muted-foreground hover:bg-accent"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="px-5 py-4">{children}</div>
      </div>
    </div>
  );
}

function CreateUserModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<UserRoleWire>('agent');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    const payload: UserCreateRequest = {
      email: email.trim(),
      name: name.trim() || null,
      role,
      password,
    };
    try {
      await authedFetch('/users', { method: 'POST', json: payload });
      onCreated();
    } catch (err) {
      setError(friendlyError(err, 'Create failed.'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="New user" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <Labeled label="Name">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-md border px-3 py-1.5 text-sm"
          />
        </Labeled>
        <Labeled label="Email" required>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-md border px-3 py-1.5 text-sm"
          />
        </Labeled>
        <Labeled label="Role" required>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as UserRoleWire)}
            className="w-full rounded-md border px-3 py-1.5 text-sm"
          >
            <option value="agent">Agent</option>
            <option value="admin">Admin</option>
          </select>
        </Labeled>
        <Labeled label="Initial password (min 8 chars)" required>
          <div className="flex gap-2">
            <input
              type={showPw ? 'text' : 'password'}
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="flex-1 rounded-md border px-3 py-1.5 text-sm"
            />
            <button
              type="button"
              onClick={() => setShowPw((s) => !s)}
              className="rounded-md border px-3 py-1.5 text-xs"
            >
              {showPw ? 'Hide' : 'Show'}
            </button>
          </div>
        </Labeled>
        {error ? (
          <p className="text-sm text-red-600">{error}</p>
        ) : null}
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border px-3 py-1.5 text-sm"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {saving ? <Spinner /> : <Check className="h-4 w-4" />} Create
          </button>
        </div>
      </form>
    </Modal>
  );
}

function EditUserModal({
  user,
  currentUserId,
  onClose,
  onSaved,
}: {
  user: UserListItem;
  currentUserId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isSelf = user.id === currentUserId;
  const [name, setName] = useState(user.name ?? '');
  const [email, setEmail] = useState(user.email);
  const [role, setRole] = useState<UserRoleWire>(user.role);
  const [isActive, setIsActive] = useState(user.is_active);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showReset, setShowReset] = useState(false);

  const diff: UserUpdateRequest = useMemo(() => {
    const out: UserUpdateRequest = {};
    if ((name || null) !== (user.name ?? null)) out.name = name || null;
    if (email !== user.email) out.email = email;
    if (role !== user.role) out.role = role;
    if (isActive !== user.is_active) out.is_active = isActive;
    return out;
  }, [name, email, role, isActive, user]);

  const hasChanges = Object.keys(diff).length > 0;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!hasChanges) return;
    setSaving(true);
    setError(null);
    try {
      await authedFetch(`/users/${user.id}`, { method: 'PATCH', json: diff });
      onSaved();
    } catch (err) {
      setError(friendlyError(err, 'Save failed.'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={`Edit user — ${user.email}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <Labeled label="Name">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-md border px-3 py-1.5 text-sm"
          />
        </Labeled>
        <Labeled label="Email">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-md border px-3 py-1.5 text-sm"
          />
        </Labeled>
        <Labeled label="Role">
          <select
            value={role}
            disabled={isSelf}
            onChange={(e) => setRole(e.target.value as UserRoleWire)}
            className="w-full rounded-md border px-3 py-1.5 text-sm disabled:bg-gray-50"
          >
            <option value="agent">Agent</option>
            <option value="admin">Admin</option>
          </select>
          {isSelf ? (
            <p className="mt-1 text-xs text-muted-foreground">
              You cannot change your own role.
            </p>
          ) : null}
        </Labeled>
        <Labeled label="Status">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={isActive}
              disabled={isSelf}
              onChange={(e) => setIsActive(e.target.checked)}
            />
            Active
          </label>
          {isSelf ? (
            <p className="mt-1 text-xs text-muted-foreground">
              You cannot deactivate your own account.
            </p>
          ) : null}
        </Labeled>

        <SectionAccessEditor userId={user.id} />

        {error ? <p className="text-sm text-red-600">{error}</p> : null}

        <div className="flex items-center justify-between gap-2 pt-2">
          <button
            type="button"
            onClick={() => setShowReset(true)}
            className="inline-flex items-center gap-1 rounded-md border px-3 py-1.5 text-xs text-amber-700"
          >
            <KeyRound className="h-3.5 w-3.5" /> Reset password
          </button>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border px-3 py-1.5 text-sm"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!hasChanges || saving}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-50"
            >
              {saving ? <Spinner /> : <Check className="h-4 w-4" />} Save
            </button>
          </div>
        </div>
      </form>

      {showReset ? (
        <ResetPasswordModal
          userId={user.id}
          userEmail={user.email}
          onClose={() => setShowReset(false)}
          onDone={() => {
            setShowReset(false);
            // password change does not affect the list, but we close edit too
            // so the admin sees a clean state.
            onSaved();
          }}
        />
      ) : null}
    </Modal>
  );
}

function ResetPasswordModal({
  userId,
  userEmail,
  onClose,
  onDone,
}: {
  userId: string;
  userEmail: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payload: PasswordResetRequest = { password };
      await authedFetch(`/users/${userId}/reset-password`, {
        method: 'POST',
        json: payload,
      });
      onDone();
    } catch (err) {
      setError(friendlyError(err, 'Reset failed.'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={`Reset password for ${userEmail}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <p className="text-xs text-muted-foreground">
          All existing sessions for this user will be revoked immediately.
          Share the new password out-of-band.
        </p>
        <Labeled label="New password (min 8 chars)" required>
          <div className="flex gap-2">
            <input
              type={showPw ? 'text' : 'password'}
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="flex-1 rounded-md border px-3 py-1.5 text-sm"
            />
            <button
              type="button"
              onClick={() => setShowPw((s) => !s)}
              className="rounded-md border px-3 py-1.5 text-xs"
            >
              {showPw ? 'Hide' : 'Show'}
            </button>
          </div>
        </Labeled>
        {error ? <p className="text-sm text-red-600">{error}</p> : null}
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border px-3 py-1.5 text-sm"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving}
            className="inline-flex items-center gap-1.5 rounded-md bg-amber-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            {saving ? <Spinner /> : <KeyRound className="h-4 w-4" />} Reset
          </button>
        </div>
      </form>
    </Modal>
  );
}

function Labeled({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-muted-foreground">
        {label}
        {required ? <span className="ml-0.5 text-red-600">*</span> : null}
      </span>
      {children}
    </label>
  );
}

// ---------------------------------------------------------------------------
// Section Access editor (inside EditUserModal)
// ---------------------------------------------------------------------------

const SECTION_GROUPS = [
  {
    label: 'CRM',
    color: 'bg-blue-500',
    keys: ['inbox', 'contacts', 'campaigns', 'templates', 'tag-review'],
  },
  {
    label: 'Finance & Inventory',
    color: 'bg-green-500',
    keys: [
      'finance/accounts',
      'finance/journals',
      'finance/receivables',
      'finance/payables',
      'inventory/items',
      'inventory/stock',
      'inventory/procurement',
      'inventory/fulfilment',
      'reports',
    ],
  },
  {
    label: 'Admin',
    color: 'bg-red-500',
    keys: [
      'analytics',
      'settings',
      'settings/tags',
      'settings/campaign-categories',
      'users',
      'audit-logs',
    ],
  },
] as const;

const ALL_SECTION_KEYS = SECTION_GROUPS.flatMap((g) => g.keys);

function sectionLabel(key: string): string {
  const parts = key.split('/');
  return parts[parts.length - 1]
    .replace(/-/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function SectionAccessEditor({
  userId,
}: {
  userId: string;
}) {
  const [sections, setSections] = useState<string[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function load() {
      setLoading(true);
      try {
        const data = await authedFetch<{ sections: string[] }>(
          `/users/${userId}/sections`,
        );
        if (active) setSections(data.sections);
      } catch {
        if (active) setError('Failed to load sections.');
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    return () => {
      active = false;
    };
  }, [userId]);

  const toggle = (key: string) => {
    setSections((prev) => {
      if (!prev) return prev;
      if (prev.includes(key)) return prev.filter((k) => k !== key);
      return [...prev, key];
    });
  };

  async function save() {
    if (!sections) return;
    setSaving(true);
    setError(null);
    try {
      await authedFetch(`/users/${userId}/sections`, {
        method: 'PUT',
        json: { sections },
      });
    } catch (err) {
      setError(friendlyError(err, 'Failed to save sections.'));
    } finally {
      setSaving(false);
    }
  }

  const hasChanges = sections !== null;

  return (
    <div className="rounded-md border bg-gray-50/50 p-4">
      <h4 className="mb-3 text-sm font-semibold">Section Access</h4>
      {loading ? (
        <SkeletonRows rows={4} />
      ) : !sections ? (
        <p className="text-sm text-red-600">{error}</p>
      ) : (
        <div className="space-y-3">
          {SECTION_GROUPS.map((group) => (
            <div key={group.label}>
              <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                <span
                  className={`inline-block h-2 w-2 shrink-0 rounded-full ${group.color}`}
                />
                {group.label}
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                {group.keys.map((key) => {
                  const checked = sections.includes(key);
                  return (
                    <label
                      key={key}
                      className="flex items-center gap-1.5 text-sm"
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggle(key)}
                        className="h-3.5 w-3.5"
                      />
                      {sectionLabel(key)}
                    </label>
                  );
                })}
              </div>
            </div>
          ))}
          <div className="flex items-center gap-3 pt-2">
            <button
              type="button"
              onClick={save}
              disabled={!hasChanges || saving}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50"
            >
              {saving ? <Spinner /> : <Check className="h-3.5 w-3.5" />}
              Save Sections
            </button>
            {error ? (
              <p className="text-xs text-red-600">{error}</p>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
