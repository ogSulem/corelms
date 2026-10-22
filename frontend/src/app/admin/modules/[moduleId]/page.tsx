"use client";

import { useParams } from "next/navigation";
import { ModuleEditor } from "@/components/admin/module-editor";

export default function AdminModuleEditorPage() {
  const { moduleId } = useParams<{ moduleId: string }>();
  return <ModuleEditor key={moduleId} moduleId={moduleId} />;
}
