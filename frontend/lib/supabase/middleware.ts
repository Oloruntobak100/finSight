import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

function missingSupabaseEnv(): boolean {
  return !process.env.NEXT_PUBLIC_SUPABASE_URL || !process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
}

export async function updateSession(request: NextRequest) {
  if (missingSupabaseEnv()) {
    // Avoid MIDDLEWARE_INVOCATION_FAILED when Vercel env vars are not set yet.
    console.error(
      "Missing NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY — set them in Vercel → Settings → Environment Variables, then redeploy."
    );
    return NextResponse.next({ request });
  }

  let supabaseResponse = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
          supabaseResponse = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options)
          );
        },
      },
    }
  );

  // getSession reads the cookie locally — getUser() hits Supabase on every navigation
  let user = null;
  try {
    const {
      data: { session },
    } = await supabase.auth.getSession();
    user = session?.user ?? null;
  } catch (err) {
    console.error("Supabase middleware getSession failed:", err);
    return supabaseResponse;
  }

  const isAuthRoute =
    request.nextUrl.pathname.startsWith("/login") ||
    request.nextUrl.pathname.startsWith("/register") ||
    request.nextUrl.pathname.startsWith("/forgot-password");

  const isProtected =
    request.nextUrl.pathname.startsWith("/dashboard") ||
    request.nextUrl.pathname === "/" ||
    request.nextUrl.pathname.startsWith("/chat") ||
    request.nextUrl.pathname.startsWith("/accounts") ||
    request.nextUrl.pathname.startsWith("/forecast") ||
    request.nextUrl.pathname.startsWith("/subscriptions") ||
    request.nextUrl.pathname.startsWith("/reports") ||
    request.nextUrl.pathname.startsWith("/settings") ||
    request.nextUrl.pathname.startsWith("/onboarding");

  if (!user && isProtected && !isAuthRoute) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    return NextResponse.redirect(url);
  }

  if (user && isAuthRoute) {
    const url = request.nextUrl.clone();
    url.pathname = "/";
    return NextResponse.redirect(url);
  }

  return supabaseResponse;
}
