'use client';

import { useEffect } from 'react';
import { ErrorBox } from '@/components/shared/ui';
import { PageHeader } from '@/components/shared/PageHeader';

export default function SettingsError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('Settings page crashed:', error);
  }, [error]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description="System-level configuration and feature flags."
      />
      <ErrorBox
        message={`Something went wrong: ${error.message || 'unknown error'}`}
        onRetry={reset}
      />
    </div>
  );
}
