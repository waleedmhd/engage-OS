'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import { apiFetch } from '@/lib/api';
import { setTokens } from '@/lib/auth';
import { clearAuthCache } from '@/hooks/useAuth';
import { Brand } from '@/components/shared/Brand';
import type { AuthTokens } from '@/types/api';

type FetchError = Error & { status?: number };

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const tokens = await apiFetch<AuthTokens>('/auth/login', {
        method: 'POST',
        json: { email, password },
      });
      setTokens(tokens.access_token, tokens.refresh_token);
      clearAuthCache();
      router.push('/inbox');
    } catch (err) {
      const status = (err as FetchError).status;
      setError(
        status === 401
          ? 'Invalid credentials'
          : 'Sign in failed. Please try again.',
      );
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="flex flex-col items-center text-center">
        <Brand
          variant="full"
          size={56}
          className="flex-col gap-3 text-lg [&_span]:max-w-full"
        />
        <p className="mt-2 text-sm text-muted-foreground">
          Sign in to your dashboard
        </p>
      </div>

      <div className="space-y-1">
        <label htmlFor="email" className="text-sm font-medium">
          Email
        </label>
        <input
          id="email"
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full rounded-md border px-3 py-2 text-sm outline-none focus:border-primary"
        />
      </div>

      <div className="space-y-1">
        <label htmlFor="password" className="text-sm font-medium">
          Password
        </label>
        <input
          id="password"
          type="password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded-md border px-3 py-2 text-sm outline-none focus:border-primary"
        />
      </div>

      {error ? (
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={submitting}
        className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition-opacity disabled:opacity-60"
      >
        {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
        {submitting ? 'Signing in…' : 'Sign in'}
      </button>
    </form>
  );
}
