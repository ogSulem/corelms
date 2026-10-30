import "./globals.css";

import type { Metadata, Viewport } from "next";
import Script from "next/script";
import type { ReactNode } from "react";

import { ToastHost } from "@/components/ui/toast-host";

/**
 * Мобильный браузер: `viewport-fit=cover` убирает белые полосы у «челки»,
 * а `interactiveWidget=resizes-content` не прячет поле ввода под клавиатурой.
 */
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  interactiveWidget: "resizes-content",
  themeColor: "#ffffff",
};

export const metadata: Metadata = {
  title: "Каркас Тайги — Контроль квалификации",
  description: "Корпоративная система контроля квалификации партнёров: обучение, тестирование, прогресс и аудит.",
  icons: {
    icon: [
      { url: "/icon.svg", type: "image/svg+xml" },
      { url: "/icon.png", type: "image/png" },
    ],
    apple: "/icon.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <html lang="ru">
      <body>
        {/* Register before Next's popstate listener: a page-level listener can be
            removed by a synchronous App Router transition before it gets called. */}
        <Script id="corelms-history-guard" strategy="beforeInteractive">{`
          window.addEventListener("popstate", function(event) {
            var guard = new Event("corelms:before-history", { cancelable: true });
            if (!window.dispatchEvent(guard)) event.stopImmediatePropagation();
          }, true);
        `}</Script>
        {children}
        <ToastHost />
      </body>
    </html>
  );
}
