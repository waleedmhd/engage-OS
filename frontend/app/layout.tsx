import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'EngageOS',
  description: 'WhatsApp CRM powered by EngageOS',
  icons: { icon: '/engageos-logo.png' },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
