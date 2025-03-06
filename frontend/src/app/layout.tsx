import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "KOENOTO",
  description: "Voice Recording and Transcription App",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ja">
      <body>{children}</body>
    </html>
  );
}
