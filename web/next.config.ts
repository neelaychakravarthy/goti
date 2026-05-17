import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Chat-first rewrite: the old multi-page workflow (/start /search
  // /approve /compare /chat) is gone. Everything happens inside the
  // chat at `/` or `/c/<hunt_id>`. These redirects keep old bookmarks
  // + any stale notification target_hrefs in the DB from 404'ing.
  async redirects() {
    return [
      { source: "/start", destination: "/", permanent: true },
      { source: "/search", destination: "/", permanent: true },
      { source: "/search/:path*", destination: "/", permanent: true },
      { source: "/approve", destination: "/", permanent: true },
      { source: "/approve/:path*", destination: "/", permanent: true },
      { source: "/compare", destination: "/", permanent: true },
      { source: "/compare/:path*", destination: "/", permanent: true },
      // Legacy `?hunt_id=` query-param URL — the app no longer reads
      // hunt_id from the query; the dynamic path /c/<id> is the
      // canonical shape. Redirecting cannot inspect query params here,
      // so /chat sans-query falls back to root which auto-resolves to
      // the user's active hunt.
      { source: "/chat", destination: "/", permanent: true },
      { source: "/chat/:path*", destination: "/", permanent: true },
    ];
  },
};

export default nextConfig;
