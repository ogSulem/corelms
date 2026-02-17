"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

type Evidence = {
  type: "quiz_attempt" | "asset_view";
  timestamp: string;
  details: string;
};

export function EvidenceList({ userId }: { userId: string }) {
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const data = await apiFetch<{ events: Evidence[] }>(`/manager/users/${userId}/evidence`);
        setEvidence(data.events);
      } catch (e) {
        setError(typeof e === "string" ? e : "Не удалось загрузить подтверждения активности");
      }
    })();
  }, [userId]);

  function formatType(t: Evidence["type"]) {
    if (t === "quiz_attempt") return "ТЕСТ";
    if (t === "asset_view") return "МАТЕРИАЛ";
    return String(t);
  }

  if (error) {
    return <div className="text-sm text-red-600">{error}</div>;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Доказательства активности</CardTitle>
      </CardHeader>
      <CardContent className="text-sm">
        {evidence.length === 0 ? (
          <div className="text-zinc-600">Нет активности.</div>
        ) : (
          <div className="grid gap-2">
            {evidence.map((e, idx) => (
              <div key={idx} className="rounded-lg border border-zinc-200 px-3 py-2">
                <div className="flex items-center justify-between">
                  <div className="font-medium">{formatType(e.type)}</div>
                  <div className="text-xs text-zinc-500">{new Date(e.timestamp).toLocaleString()}</div>
                </div>
                <div className="mt-1 text-xs text-zinc-600">{e.details}</div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
