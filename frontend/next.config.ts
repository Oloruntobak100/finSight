import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

// Ensure NEXT_PUBLIC_* vars are available to Turbopack/Webpack at compile time
const { combinedEnv } = loadEnvConfig(process.cwd());

const nextConfig: NextConfig = {
  devIndicators: false,
  env: {
    NEXT_PUBLIC_SUPABASE_URL: combinedEnv.NEXT_PUBLIC_SUPABASE_URL ?? "",
    NEXT_PUBLIC_SUPABASE_ANON_KEY: combinedEnv.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "",
    NEXT_PUBLIC_FASTAPI_URL: combinedEnv.NEXT_PUBLIC_FASTAPI_URL ?? "http://localhost:8000",
    NEXT_PUBLIC_APP_URL: combinedEnv.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000",
  },
};

export default nextConfig;
