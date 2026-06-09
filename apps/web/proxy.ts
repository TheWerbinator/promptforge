import { NextResponse, type NextRequest } from "next/server";

// Next 16 renamed the `middleware` convention to `proxy`. Presence-check only: if
// the session cookie is missing on a protected route, bounce to login. The
// cookie's actual validity is enforced server-side on the next API call (and
// refreshed there) — keeping the proxy edge-light avoids decrypting/refreshing
// on every request.
const SESSION_COOKIE = "pf_session";

export function proxy(req: NextRequest): NextResponse {
  if (req.cookies.has(SESSION_COOKIE)) return NextResponse.next();
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.searchParams.set("next", req.nextUrl.pathname);
  return NextResponse.redirect(url);
}

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/prompts/:path*",
    "/evals/:path*",
    "/chat/:path*",
    "/settings/:path*",
  ],
};
