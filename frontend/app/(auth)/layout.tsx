export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-[#fafafa] px-4">
      <div className="w-full max-w-sm rounded-lg border bg-white p-8 shadow-sm">
        {children}
      </div>
      <p className="mt-6 text-xs text-muted-foreground">Powered by EngageOS</p>
    </div>
  );
}
