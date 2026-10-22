import type { Material } from "@/lib/materials";
import type { PresentationLesson } from "@/components/learning/lesson-presentation";

export type EditorModule = { id: string; title: string; description: string | null; category: string | null; is_active: boolean; is_archived: boolean; visibility: string; tag_ids: string[]; content_revision: number; final_quiz_id: string | null; final_quiz_enabled: boolean };
export type EditorLesson = PresentationLesson & { title: string; content: string; content_mode: "manual" | "import"; content_version: number; has_external_content: boolean; content_length: number | null; order: number; is_folder: boolean; is_archived: boolean; requires_quiz: boolean; quiz_id: string; question_count: number; outline_path: string | null; source_path: string | null };
export type EditorAsset = Material & { version: number; is_archived: boolean; submodule_id: string | null; source_path: string | null; created_at: string };
export type Workspace = { created_lesson_id?: string; capabilities?: { ai_configured: boolean; upload_max_bytes: number }; module: EditorModule; lessons: EditorLesson[]; assets: EditorAsset[] };
