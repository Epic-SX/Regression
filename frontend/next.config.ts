import type { NextConfig } from "next";
import withPWA from "next-pwa";

const nextConfig: NextConfig = {
  webpack: (config) => {
    config.module.rules.push({
      test: /\.worklet\.js$/,
      use: { loader: 'worklet-loader' }
    });
    return config;
  }
};

export default withPWA({
  // Next.js の設定をスプレッド
  ...nextConfig,

  // ここから先は next-pwa 用オプションをトップレベルに記載
  dest: "public", // Service Worker, workbox などの出力先
  register: true, // trueならビルド時にSWを自動登録するコードを生成
  skipWaiting: true, // 新しいSWがインストールされたら即時に有効化
  disable: process.env.NODE_ENV === "development", // 開発中にSWを無効化したい場合
});
