/** Use direct S3 downloads only when the address is usable by the user's browser. */
export function materialDownloadUrl(assetId: string, signedUrl: string, pageProtocol = "https:"): string {
  const fallback = `/api/backend/assets/${encodeURIComponent(assetId)}/download`;
  try {
    const url = new URL(signedUrl);
    const host = url.hostname.toLowerCase();
    const internal = host === "localhost" || host.endsWith(".localhost") || /^127\./.test(host) || host === "0.0.0.0" || host === "[::1]" || !host.includes(".");
    if (internal || !["http:", "https:"].includes(url.protocol) || (pageProtocol === "https:" && url.protocol !== "https:")) return fallback;
    return signedUrl;
  } catch { return fallback; }
}
