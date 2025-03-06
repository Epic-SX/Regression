/** @type {import('next').NextConfig} */
const withPWA = require('next-pwa')({
  dest: 'public',
  disable: process.env.NODE_ENV === 'development'
});

const nextConfig = withPWA({
  env: {
    NEXT_PUBLIC_KOENOTE_API_URL: process.env.NEXT_PUBLIC_KOENOTE_API_URL,
    NEXT_PUBLIC_AUDIO_BUCKET_NAME: process.env.NEXT_PUBLIC_AUDIO_BUCKET_NAME,
  }
});

module.exports = nextConfig;