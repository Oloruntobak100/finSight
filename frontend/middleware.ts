import { type NextRequest } from "next/server";
import { updateSession } from "@/lib/supabase/middleware";

export async function middleware(request: NextRequest) {
  return updateSession(request);
}

export const config = {
  matcher: [
    "/",
    "/login",
    "/register",
    "/verify-email",
    "/forgot-password",
    "/oauth/quickbooks/callback",
    "/onboarding",
    "/chat/:path*",
    "/accounts/:path*",
    "/transactions",
    "/transactions/:path*",
    "/analysis/:path*",
    "/forecast/:path*",
    "/subscriptions/:path*",
    "/reports/:path*",
    "/settings/:path*",
  ],
};
