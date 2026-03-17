import "./globals.css";

import type { Metadata } from "next";
import type { ReactNode } from "react";

import { ToastHost } from "@/components/ui/toast-host";

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
        {children}
        <ToastHost />
      </body>
    </html>
  );
}
