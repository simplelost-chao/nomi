import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["nomi.zhuchao.life"],
  generateBuildId: () => Date.now().toString(),
  async rewrites() {
    return [
      {
        source: "/admin",
        destination: "http://localhost:8100/admin",
      },
      {
        source: "/api/:path*",
        destination: "http://localhost:8100/api/:path*",
      },
    ];
  },
};

export default nextConfig;
