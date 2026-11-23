/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Не сообщаем стек наружу: X-Powered-By — подсказка для подбора уязвимостей.
  poweredByHeader: false,
  // Оптимизатор картинок Next.js приложению не нужен: `next/image` не
  // используется ни в одной странице, все превью приходят из нашего хранилища
  // готовыми файлами. Зато `/_next/image` — публичный эндпоинт, который в
  // 15.2.8 содержал неаутентифицированный RCE (CVE-2026-96889) и обрабатывал
  // чужие URL на стороне сервера. Отключаем целиком: маршрут перестаёт
  // существовать, а `sharp` больше не участвует в обработке запросов.
  images: { unoptimized: true },
  allowedDevOrigins: ["*.e2b.app"],
  async headers() {
    const cspReportOnly = [
      "default-src 'self'",
      "base-uri 'self'",
      "object-src 'none'",
      ...(process.env.NODE_ENV === "development" ? [] : ["frame-ancestors 'none'"]),
      "frame-src 'self'",
      "form-action 'self'",
      "img-src 'self' data: blob:",
      "font-src 'self' data:",
      "style-src 'self' 'unsafe-inline'",
      "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
      "connect-src 'self' https: http:",
      "media-src 'self' blob: data: https: http:",
    ].join('; ');

    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          ...(process.env.NODE_ENV === 'development' ? [] : [{ key: 'X-Frame-Options', value: 'DENY' }]),
          { key: 'Referrer-Policy', value: 'no-referrer' },
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
          { key: 'Cross-Origin-Opener-Policy', value: 'same-origin' },
          { key: 'Cross-Origin-Resource-Policy', value: 'same-origin' },
          { key: 'Content-Security-Policy-Report-Only', value: cspReportOnly },
        ],
      },
      {
        source: '/api/backend/assets/:assetId/stream',
        headers: [
          { key: 'X-Frame-Options', value: 'SAMEORIGIN' },
          { key: 'Content-Security-Policy-Report-Only', value: "frame-ancestors 'self'" },
        ],
      },
    ];
  },
};

module.exports = nextConfig;
