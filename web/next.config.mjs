/** @type {import('next').NextConfig} */
const nextConfig = {
  // This spoke is proxied at whosyurgoat.app/election by the hub's vercel.json.
  basePath: '/election',
  assetPrefix: '/election',
};

export default nextConfig;
