import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { isJwtValid } from '@/lib/jwt';

/**
 * Cookie-based auth guard. The access token is mirrored into a JS-readable
 * cookie on login so this Edge middleware can check auth without an API call.
 *
 * Authentication is decided by the JWT's `exp`, not cookie presence: the
 * login cookie outlives the token, and a stale-but-present cookie used to
 * redirect returning users off /login forever.
 */
export function middleware(request: NextRequest) {
  const authed = isJwtValid(request.cookies.get('access_token')?.value);
  const { pathname } = request.nextUrl;
  const isLoginPage = pathname === '/login';

  if (!authed && !isLoginPage) {
    const url = request.nextUrl.clone();
    url.pathname = '/login';
    return NextResponse.redirect(url);
  }

  if (authed && isLoginPage) {
    const url = request.nextUrl.clone();
    url.pathname = '/inbox';
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  // Exclude Next.js internals, API routes, and any public static assets
  // (images, fonts, etc.) so unauthenticated requests for files like
  // /engageos-logo.svg are served directly rather than redirected to /login.
  matcher: ['/((?!_next/static|_next/image|favicon.ico|api/|.*\\.(?:png|jpg|jpeg|gif|svg|ico|webp|woff2?|ttf|otf)).*)'],
};
