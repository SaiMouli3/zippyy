import { NextRequest, NextResponse } from "next/server";

// Cheap edge gate: without a session cookie there is nothing to render, so send people to sign in first.
// The cookie's validity is still checked by the API on every request; this only avoids a flash of the shell.
export function middleware(req: NextRequest) {
  if (req.cookies.get("zpy_session")) return NextResponse.next();
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = `?next=${encodeURIComponent(req.nextUrl.pathname + req.nextUrl.search)}`;
  return NextResponse.redirect(url);
}

export const config = {
  matcher: [
    "/overview/:path*", "/ndr/:path*", "/shipments/:path*", "/pre-delivery/:path*", "/conversations/:path*",
    "/calls/:path*", "/agent-activity/:path*", "/escalations/:path*", "/analytics/:path*", "/integrations/:path*",
    "/agent-config/:path*", "/policies/:path*", "/audit/:path*", "/settings/:path*",
  ],
};
