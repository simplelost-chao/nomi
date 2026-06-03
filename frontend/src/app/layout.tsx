import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NOMI 诺米",
  description: "memory. warmth. with you.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet" />
      </head>
      <body className="noise min-h-screen">
        {/* Background glows */}
        <div className="nomi-bg-glow" />
        <div className="nomi-bg-glow-2" />
        {/* Content */}
        <main className="relative mx-auto max-w-md px-5 py-8 md:max-w-2xl lg:max-w-4xl">{children}</main>
      </body>
    </html>
  );
}
