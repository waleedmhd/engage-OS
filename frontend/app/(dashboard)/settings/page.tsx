'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Check, ChevronDown, ChevronRight, Download } from 'lucide-react';
import clsx from 'clsx';
import { PageHeader } from '@/components/shared/PageHeader';
import {
  ErrorBox,
  PermissionState,
  SkeletonRows,
  Spinner,
} from '@/components/shared/ui';
import { authedFetch } from '@/lib/authedFetch';
import { getAccessToken, refreshTokens } from '@/lib/auth';
import { env } from '@/lib/env';
import { useAuth } from '@/hooks/useAuth';
import type {
  AISettingsResponse,
  AISettingsUpdateRequest,
  BusinessHoursSetting,
  CampaignDailyCapSetting,
  OperationalSettingsResponse,
  OperationalSettingsUpdateRequest,
  ReadOnlyModeSetting,
  SettingResponse,
  TimezoneSetting,
} from '@/types/api';

type FetchError = Error & { status?: number; payload?: unknown };

const HHMM_RE = /^([01]\d|2[0-3]):[0-5]\d$/;

function formatServerError(err: unknown, fallback: string): string {
  const e = err as FetchError;
  const payload = e?.payload as
    | { detail?: unknown; error?: { message?: string } }
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
  if (payload?.error?.message) return payload.error.message;
  return e?.message || fallback;
}

function getTimezones(): string[] {
  try {
    const fn = (Intl as { supportedValuesOf?: (k: string) => string[] })
      .supportedValuesOf;
    if (typeof fn === 'function') return fn('timeZone');
  } catch {
    // ignore
  }
  return [
    'UTC',
    'Asia/Dubai',
    'Asia/Riyadh',
    'Asia/Kolkata',
    'Asia/Singapore',
    'Europe/London',
    'Europe/Paris',
    'America/New_York',
    'America/Los_Angeles',
  ];
}

export default function SettingsPage() {
  const { user, isLoading: authLoading } = useAuth();
  const isAdmin = user?.role === 'admin';

  if (authLoading) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Settings"
          description="System-level configuration and feature flags."
        />
        <SkeletonRows rows={6} />
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Settings"
          description="System-level configuration and feature flags."
        />
        <PermissionState title="Admin only" />
      </div>
    );
  }

  return <SettingsAdminView />;
}

function SettingsAdminView() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description="System-level configuration and feature flags."
      />
      <AISection />
      <OperationalSection />
      <AdvancedSection />
      <ExportSection />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: AI
// ---------------------------------------------------------------------------

function AISection() {
  const [state, setState] = useState<AISettingsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [testInput, setTestInput] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setState(await authedFetch<AISettingsResponse>('/settings/ai'));
    } catch (err) {
      setError(formatServerError(err, 'Failed to load AI settings.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function update(patch: AISettingsUpdateRequest, key: string) {
    if (!state) return;
    const prev = state;
    setState({ ...state, ...patch });
    setSavingKey(key);
    setError(null);
    try {
      const next = await authedFetch<AISettingsResponse>('/settings/ai', {
        method: 'PUT',
        json: patch,
      });
      setState(next);
    } catch (err) {
      setState(prev);
      setError(formatServerError(err, 'Failed to update AI settings.'));
    } finally {
      setSavingKey(null);
    }
  }

  function addTestNumber() {
    if (!state) return;
    const trimmed = testInput.trim();
    if (!trimmed) return;
    if (state.test_numbers.includes(trimmed)) {
      setTestInput('');
      return;
    }
    const next = [...state.test_numbers, trimmed];
    setTestInput('');
    update({ test_numbers: next }, 'test_numbers');
  }

  function removeTestNumber(idx: number) {
    if (!state) return;
    const next = state.test_numbers.filter((_, i) => i !== idx);
    update({ test_numbers: next }, 'test_numbers');
  }

  return (
    <Card title="AI" description="Global controls for AI features — kill switch, test numbers, and per-feature toggles.">
      {loading || !state ? (
        <SkeletonRows rows={5} />
      ) : (
        <>
          {error ? <ErrorBox message={error} onRetry={load} /> : null}
          <ToggleRow
            label="Kill switch"
            description="When ON, all AI features are disabled for every contact except the test numbers listed below."
            checked={state.kill_switch}
            saving={savingKey === 'kill_switch'}
            onChange={(v) => update({ kill_switch: v }, 'kill_switch')}
            danger
          />

          {/* Test numbers — exempt from kill switch */}
          <div className="space-y-2">
            <div className="text-sm font-medium">Test numbers</div>
            <p className="text-xs text-muted-foreground">
              Phone numbers that bypass the kill switch. AI features remain active for these contacts even when the kill switch is ON.
            </p>
            {state.test_numbers.length > 0 ? (
              <ul className="space-y-1">
                {state.test_numbers.map((num, i) => (
                  <li key={i} className="flex items-center gap-2 text-sm">
                    <code className="rounded bg-gray-100 px-2 py-0.5 text-xs">{num}</code>
                    <button
                      type="button"
                      disabled={savingKey === 'test_numbers'}
                      onClick={() => removeTestNumber(i)}
                      className="text-xs text-red-600 hover:text-red-800 disabled:opacity-50"
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-muted-foreground italic">No test numbers configured.</p>
            )}
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={testInput}
                onChange={(e) => setTestInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') addTestNumber(); }}
                placeholder="+1234567890"
                disabled={savingKey === 'test_numbers'}
                className="w-48 rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
              />
              <button
                type="button"
                onClick={addTestNumber}
                disabled={savingKey === 'test_numbers' || !testInput.trim()}
                className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50"
              >
                {savingKey === 'test_numbers' ? 'Saving…' : 'Add'}
              </button>
            </div>
          </div>

          <ToggleRow
            label="Tag suggestions"
            description="When OFF, the AI will not generate tag suggestions for contacts."
            checked={state.tag_suggestions_enabled}
            saving={savingKey === 'tag_suggestions_enabled'}
            onChange={(v) =>
              update({ tag_suggestions_enabled: v }, 'tag_suggestions_enabled')
            }
          />
          <ToggleRow
            label="Response generation"
            description="When OFF, the AI will not generate any reply drafts. Tag suggestions may still be produced if enabled above."
            checked={state.response_generation_enabled}
            saving={savingKey === 'response_generation_enabled'}
            onChange={(v) =>
              update({ response_generation_enabled: v }, 'response_generation_enabled')
            }
          />
          <ToggleRow
            label="Auto-send enabled"
            description="When OFF, AI drafts always require human approval before sending."
            checked={state.auto_send_enabled}
            saving={savingKey === 'auto_send_enabled'}
            onChange={(v) =>
              update({ auto_send_enabled: v }, 'auto_send_enabled')
            }
          />
        </>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Section: Operational
// ---------------------------------------------------------------------------

function OperationalSection() {
  const [server, setServer] = useState<OperationalSettingsResponse | null>(
    null,
  );
  const [draft, setDraft] = useState<OperationalSettingsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [savedKey, setSavedKey] = useState<string | null>(null);

  const timezones = useMemo(() => getTimezones(), []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await authedFetch<OperationalSettingsResponse>(
        '/settings/operational',
      );
      setServer(data);
      setDraft(data);
    } catch (err) {
      setError(formatServerError(err, 'Failed to load operational settings.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function save<K extends keyof OperationalSettingsResponse>(
    key: K,
    value: OperationalSettingsResponse[K],
  ) {
    if (!server) return;
    const patch = { [key]: value } as OperationalSettingsUpdateRequest;
    const prevServer = server;
    setServer({ ...server, [key]: value });
    setSavingKey(String(key));
    setError(null);
    try {
      const next = await authedFetch<OperationalSettingsResponse>(
        '/settings/operational',
        { method: 'PUT', json: patch },
      );
      setServer(next);
      setDraft(next);
      setSavedKey(String(key));
      setTimeout(() => setSavedKey(null), 2000);
    } catch (err) {
      setServer(prevServer);
      setDraft(prevServer);
      setError(
        formatServerError(err, `Failed to update ${String(key)}.`),
      );
    } finally {
      setSavingKey(null);
    }
  }

  return (
    <Card
      title="Operational"
      description="Read-only mode, timezone, business hours, and campaign throttling."
    >
      {loading || !draft || !server ? (
        <SkeletonRows rows={4} />
      ) : (
        <div className="space-y-6">
          {error ? <ErrorBox message={error} onRetry={load} /> : null}

          {/* Read-only mode */}
          <div className="space-y-2">
            <ToggleRow
              label="Read-only mode"
              description="When ON, all mutating API calls return 503. Use during incidents or migrations."
              checked={draft.read_only_mode.enabled}
              saving={savingKey === 'read_only_mode'}
              saved={savedKey === 'read_only_mode'}
              onChange={(v) => {
                const next: ReadOnlyModeSetting = { enabled: v };
                setDraft({ ...draft, read_only_mode: next });
                save('read_only_mode', next);
              }}
              danger
            />
            {draft.read_only_mode.enabled ? (
              <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>
                  Read-only mode is active. All mutating endpoints will return
                  HTTP 503 across the cluster within ~10 seconds. Toggling this
                  setting itself is exempt from the gate.
                </span>
              </div>
            ) : null}
          </div>

          {/* Timezone */}
          <Field
            label="Timezone"
            description="IANA name; controls business-hours math (DSD §10). Default Asia/Dubai."
            saving={savingKey === 'timezone'}
            saved={savedKey === 'timezone'}
          >
            <select
              className="w-full max-w-sm rounded-md border px-3 py-2 text-sm"
              value={draft.timezone.tz}
              onChange={(e) => {
                const next: TimezoneSetting = { tz: e.target.value };
                setDraft({ ...draft, timezone: next });
                save('timezone', next);
              }}
            >
              {timezones.map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </select>
          </Field>

          {/* Business hours */}
          <BusinessHoursField
            value={draft.business_hours}
            saving={savingKey === 'business_hours'}
            saved={savedKey === 'business_hours'}
            onChange={(next) => {
              setDraft({ ...draft, business_hours: next });
            }}
            onCommit={(next) => save('business_hours', next)}
          />

          {/* Campaign daily cap */}
          <CampaignCapField
            value={draft.campaign_daily_cap}
            saving={savingKey === 'campaign_daily_cap'}
            saved={savedKey === 'campaign_daily_cap'}
            onChange={(next) => {
              setDraft({ ...draft, campaign_daily_cap: next });
            }}
            onCommit={(next) => save('campaign_daily_cap', next)}
          />
        </div>
      )}
    </Card>
  );
}

function BusinessHoursField({
  value,
  saving,
  saved,
  onChange,
  onCommit,
}: {
  value: BusinessHoursSetting;
  saving: boolean;
  saved: boolean;
  onChange: (v: BusinessHoursSetting) => void;
  onCommit: (v: BusinessHoursSetting) => void;
}) {
  const [localError, setLocalError] = useState<string | null>(null);

  function validateAndCommit(next: BusinessHoursSetting) {
    if (!HHMM_RE.test(next.start) || !HHMM_RE.test(next.end)) {
      setLocalError('Times must be in HH:MM 24-hour format.');
      return;
    }
    if (next.end <= next.start) {
      setLocalError('End must be after start.');
      return;
    }
    setLocalError(null);
    onCommit(next);
  }

  return (
    <Field
      label="Business hours"
      description="Outside these hours, campaigns defer instead of dispatching."
      saving={saving}
      saved={saved}
    >
      <div className="space-y-2">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={value.enabled}
            onChange={(e) => {
              const next = { ...value, enabled: e.target.checked };
              onChange(next);
              validateAndCommit(next);
            }}
          />
          Enforce business hours
        </label>
        <div
          className={clsx(
            'flex flex-wrap items-center gap-3',
            !value.enabled && 'opacity-50',
          )}
        >
          <div className="flex items-center gap-2 text-sm">
            <span className="text-xs text-muted-foreground">Start</span>
            <input
              type="time"
              value={value.start}
              onChange={(e) => onChange({ ...value, start: e.target.value })}
              onBlur={() => validateAndCommit(value)}
              className="rounded-md border px-2 py-1 text-sm"
            />
          </div>
          <div className="flex items-center gap-2 text-sm">
            <span className="text-xs text-muted-foreground">End</span>
            <input
              type="time"
              value={value.end}
              onChange={(e) => onChange({ ...value, end: e.target.value })}
              onBlur={() => validateAndCommit(value)}
              className="rounded-md border px-2 py-1 text-sm"
            />
          </div>
        </div>
        {localError ? (
          <p className="text-xs text-red-600">{localError}</p>
        ) : null}
      </div>
    </Field>
  );
}

function CampaignCapField({
  value,
  saving,
  saved,
  onChange,
  onCommit,
}: {
  value: CampaignDailyCapSetting;
  saving: boolean;
  saved: boolean;
  onChange: (v: CampaignDailyCapSetting) => void;
  onCommit: (v: CampaignDailyCapSetting) => void;
}) {
  const [localError, setLocalError] = useState<string | null>(null);

  function validateAndCommit(next: CampaignDailyCapSetting) {
    if (!Number.isInteger(next.limit) || next.limit <= 0) {
      setLocalError('Limit must be a positive integer.');
      return;
    }
    setLocalError(null);
    onCommit(next);
  }

  return (
    <Field
      label="Campaign daily cap"
      description="Cluster-wide maximum outbound campaign messages per day. DSD §10 default: 800."
      saving={saving}
      saved={saved}
    >
      <div className="space-y-2">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={value.enabled}
            onChange={(e) => {
              const next = { ...value, enabled: e.target.checked };
              onChange(next);
              validateAndCommit(next);
            }}
          />
          Enforce daily cap
        </label>
        <div className={clsx('flex items-center gap-2', !value.enabled && 'opacity-50')}>
          <input
            type="number"
            min={1}
            value={value.limit}
            onChange={(e) =>
              onChange({ ...value, limit: Number(e.target.value) })
            }
            onBlur={() => validateAndCommit(value)}
            className="w-32 rounded-md border px-3 py-1 text-sm"
          />
          <span className="text-xs text-muted-foreground">messages / day</span>
        </div>
        {localError ? (
          <p className="text-xs text-red-600">{localError}</p>
        ) : null}
      </div>
    </Field>
  );
}

// ---------------------------------------------------------------------------
// Section: Advanced
// ---------------------------------------------------------------------------

function AdvancedSection() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<SettingResponse[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await authedFetch<SettingResponse[]>('/settings'));
    } catch (err) {
      setError(formatServerError(err, 'Failed to load raw settings.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open && items === null) load();
  }, [open, items, load]);

  return (
    <div className="rounded-lg border bg-white">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-5 py-4 text-left"
      >
        <div>
          <h2 className="text-base font-semibold">Advanced (raw key/value)</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            All settings rows. Edit JSON values directly — for keys not covered
            above (e.g. campaign rate-per-second).
          </p>
        </div>
        {open ? (
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        )}
      </button>
      {open ? (
        <div className="border-t px-5 py-4">
          {loading ? (
            <SkeletonRows rows={4} />
          ) : error ? (
            <ErrorBox message={error} onRetry={load} />
          ) : items && items.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No settings rows yet.
            </p>
          ) : items ? (
            <div className="space-y-3">
              {items.map((row) => (
                <RawSettingRow
                  key={row.key}
                  row={row}
                  onSaved={(updated) =>
                    setItems((prev) =>
                      (prev ?? []).map((r) =>
                        r.key === updated.key ? updated : r,
                      ),
                    )
                  }
                />
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function RawSettingRow({
  row,
  onSaved,
}: {
  row: SettingResponse;
  onSaved: (r: SettingResponse) => void;
}) {
  const [text, setText] = useState(() => JSON.stringify(row.value, null, 2));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const dirty = text !== JSON.stringify(row.value, null, 2);

  async function save() {
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      setError('Invalid JSON.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await authedFetch<SettingResponse>(
        `/settings/${encodeURIComponent(row.key)}`,
        { method: 'PUT', json: { value: parsed } },
      );
      onSaved(updated);
      setText(JSON.stringify(updated.value, null, 2));
      setSavedAt(Date.now());
      setTimeout(() => setSavedAt(null), 2000);
    } catch (err) {
      setError(formatServerError(err, 'Save failed.'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-md border p-3">
      <div className="mb-2 flex items-center justify-between">
        <code className="text-xs font-medium">{row.key}</code>
        <span className="text-[10px] uppercase text-muted-foreground">
          {row.scope}
        </span>
      </div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={Math.min(8, Math.max(2, text.split('\n').length))}
        spellCheck={false}
        className="w-full rounded-md border bg-gray-50 px-3 py-2 font-mono text-xs"
      />
      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          onClick={save}
          disabled={!dirty || saving}
          className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        {savedAt ? (
          <span className="flex items-center gap-1 text-xs text-green-700">
            <Check className="h-3 w-3" /> Saved
          </span>
        ) : null}
        {error ? <span className="text-xs text-red-600">{error}</span> : null}
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Section: Chat History Export
// ---------------------------------------------------------------------------

function ExportSection() {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleExport() {
    setDownloading(true);
    setError(null);
    try {
      let token = getAccessToken();
      let resp = await fetch(`${env.apiUrl}/settings/export/chat-history`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (resp.status === 401) {
        await refreshTokens();
        token = getAccessToken();
        resp = await fetch(`${env.apiUrl}/settings/export/chat-history`, {
          headers: { Authorization: `Bearer ${token}` },
        });
      }
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `HTTP ${resp.status}`);
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const disposition = resp.headers.get("Content-Disposition");
      const match = disposition?.match(/filename="?([^"]+)"?$/);
      const a = document.createElement("a");
      a.href = url;
      a.download = match?.[1] ?? "chat-history.jsonl";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      setError((err as Error).message || "Export failed.");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <Card
      title="Chat History Export"
      description="Download all conversation data as JSONL for AI training or data analysis."
    >
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleExport}
          disabled={downloading}
          className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {downloading ? (
            <>
              <Spinner /> Downloading…
            </>
          ) : (
            <>
              <Download className="h-4 w-4" /> Export All Chat History
            </>
          )}
        </button>
      </div>
      {error ? <p className="text-xs text-red-600">{error}</p> : null}
    </Card>
  );
}
// ---------------------------------------------------------------------------
// Shared primitives
// ---------------------------------------------------------------------------

function Card({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border bg-white">
      <header className="border-b px-5 py-4">
        <h2 className="text-base font-semibold">{title}</h2>
        {description ? (
          <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
        ) : null}
      </header>
      <div className="space-y-4 px-5 py-4">{children}</div>
    </section>
  );
}

function ToggleRow({
  label,
  description,
  checked,
  saving,
  saved,
  onChange,
  danger,
}: {
  label: string;
  description?: string;
  checked: boolean;
  saving?: boolean;
  saved?: boolean;
  onChange: (v: boolean) => void;
  danger?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <div className="flex items-center gap-2 text-sm font-medium">
          {label}
          {saving ? <Spinner /> : null}
          {saved ? (
            <span className="flex items-center gap-1 text-xs font-normal text-green-700">
              <Check className="h-3 w-3" /> Saved
            </span>
          ) : null}
        </div>
        {description ? (
          <p className="mt-0.5 max-w-xl text-xs text-muted-foreground">
            {description}
          </p>
        ) : null}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={saving}
        onClick={() => onChange(!checked)}
        className={clsx(
          'relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors',
          checked
            ? danger
              ? 'bg-red-600'
              : 'bg-primary'
            : 'bg-gray-300',
          saving && 'opacity-60',
        )}
      >
        <span
          className={clsx(
            'inline-block h-4 w-4 transform rounded-full bg-white transition-transform',
            checked ? 'translate-x-6' : 'translate-x-1',
          )}
        />
      </button>
    </div>
  );
}

function Field({
  label,
  description,
  saving,
  saved,
  children,
}: {
  label: string;
  description?: string;
  saving?: boolean;
  saved?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2 text-sm font-medium">
        {label}
        {saving ? <Spinner /> : null}
        {saved ? (
          <span className="flex items-center gap-1 text-xs font-normal text-green-700">
            <Check className="h-3 w-3" /> Saved
          </span>
        ) : null}
      </div>
      {description ? (
        <p className="text-xs text-muted-foreground">{description}</p>
      ) : null}
      <div className="pt-1">{children}</div>
    </div>
  );
}
