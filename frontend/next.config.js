/** @type {import('next').NextConfig} */
const nextConfig = {
  env: {
    NEXT_PUBLIC_KOENOTE_API_URL: process.env.NEXT_PUBLIC_KOENOTE_API_URL,
    NEXT_PUBLIC_AUDIO_BUCKET_NAME: process.env.NEXT_PUBLIC_AUDIO_BUCKET_NAME,
  },
}

module.exports = nextConfig 