'use client';

import { useEffect } from 'react';
import { ErrorBox } from '@/components/shared/ui';
import { PageHeader } from '@/components/shared/PageHeader';

/**
 * Route-segment error boundary for every dashboard page (inbox, contacts,
 * campaigns, templates, etc.). A render error in any of them — e.g. calling
 * `.map` on an API payload whose shape doesn't match what the component
 * expects — is caught here and shown as a retry box instead of blanking the
 * whole app with a white screen. A more specific boundary (e.g.
 * `settings/error.tsx`) takes precedence for its own subtree.
 */
export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('Dashboard page crashed:', error);
  }, [error]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Something went wrong"
        description="This page hit an unexpected error. Try again, or reload if it persists."
      />
      <ErrorBox
        message={`Something went wrong: ${error.message || 'unknown error'}`}
        onRetry={reset}
      />
    </div>
  );
}
