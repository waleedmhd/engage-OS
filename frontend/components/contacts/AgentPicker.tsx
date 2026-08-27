'use client';

import type { UserResponse } from '@/types/api';

export const AI_AGENT_SENTINEL = '__ai_agent__';

interface AgentPickerProps {
  users: UserResponse[];
  value: string | null;
  onChange: (value: string | null) => void;
  includeUnassigned?: boolean;
  includeAI?: boolean;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
}

export function AgentPicker({
  users,
  value,
  onChange,
  includeUnassigned = false,
  includeAI = false,
  placeholder = 'Select agent…',
  disabled = false,
  className = '',
}: AgentPickerProps) {
  return (
    <select
      value={value ?? ''}
      disabled={disabled}
      onChange={(e) =>
        onChange(e.target.value === '' ? null : e.target.value)
      }
      className={`rounded-md border px-3 py-2 text-sm ${className}`}
    >
      <option value="" disabled={!includeUnassigned}>
        {includeUnassigned ? '— Unassigned —' : placeholder}
      </option>
      {includeAI && (
        <option value={AI_AGENT_SENTINEL}>AI Agent</option>
      )}
      {users.map((u) => (
        <option key={u.id} value={u.id}>
          {u.name ? `${u.name} (${u.email})` : u.email}
          {u.is_active ? '' : ' [inactive]'}
        </option>
      ))}
    </select>
  );
}
