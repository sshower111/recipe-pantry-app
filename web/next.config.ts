import type { NextConfig } from "next";

// The FastAPI server (`uvicorn api.app:app --port 8000` from the project root).
const API_ORIGIN = process.env.RECIPE_API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
};

export default nextConfig;
