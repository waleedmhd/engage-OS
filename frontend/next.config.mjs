/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  poweredByHeader: false,
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
    NEXT_PUBLIC_WS_URL: process.env.NEXT_PUBLIC_WS_URL,
  },
  async rewrites() {
    const backend = process.env.BACKEND_URL || 'http://localhost:8000';
    return [
      {
        source: '/proxy/api/:path*',
        destination: `${backend}/api/:path*`,
      },
      {
        source: '/proxy/webhooks/:path*',
        destination: `${backend}/webhooks/:path*`,
      },
    ];
  },
};

export default nextConfig;
