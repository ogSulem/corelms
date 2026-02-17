import "./globals.css";

import type { Metadata } from "next";

import { ToastHost } from "@/components/ui/toast-host";

export const metadata: Metadata = {
  title: "Каркас Тайги — Контроль квалификации",
  description: "Корпоративная система контроля квалификации сотрудников: обучение, тестирование, прогресс и аудит.",
  icons: {
    icon: "/icon.png",
    apple: "/icon.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
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
