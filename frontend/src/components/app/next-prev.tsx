"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";

export function NextPrevNav({
  currentOrder,
  total,
  moduleId,
  prevSubmoduleId,
  nextSubmoduleId,
}: {
  currentOrder: number;
  total: number;
  moduleId: string;
  prevSubmoduleId: string | null;
  nextSubmoduleId: string | null;
}) {
  void currentOrder;
  void total;
  void moduleId;
  void prevSubmoduleId;
  void nextSubmoduleId;
  return null;
}
