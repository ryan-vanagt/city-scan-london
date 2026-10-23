import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  turbopack: {
    root: ".",
  },
};

export default nextConfig;
