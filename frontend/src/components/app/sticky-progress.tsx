"use client";

import { Progress } from "@/components/ui/progress";

export function StickyProgressBar({
  moduleId,
  moduleTitle,
  passed,
  total,
}: {
  moduleId: string;
  moduleTitle?: string;
  passed: number;
  total: number;
}) {
  const pct = total > 0 ? Math.round((passed / total) * 100) : 0;

  return (
    <div className="sticky top-[58px] z-10 border-b border-zinc-200/80 bg-white/70 backdrop-blur-xl">
      <div className="mx-auto max-w-6xl px-6 py-3">
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <div className="text-xs text-zinc-600">{moduleTitle || "Прогресс модуля"}</div>
            <div className="mt-1 flex items-center gap-3">
              <div className="w-64 max-w-[50vw]">
                <Progress value={pct} />
              </div>
              <div className="text-sm font-medium tabular-nums">
                {pct}%
                <span className="ml-2 text-xs text-zinc-600">
                  {passed}/{total}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
