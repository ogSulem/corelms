export type TabKey = "modules" | "import" | "analytics" | "users" | "diagnostics";

export type ImportJobItem = {
  job_id: string;
  object_key?: string;
  title?: string;
  source_filename?: string;
  module_id?: string;
  module_title?: string;
  created_at?: string;
  status?: string;
  stage?: string;
  stage_at?: string;
  detail?: string;
  error_code?: string;
  error_hint?: string;
  error_message?: string;
  error?: string | null;
};

export type RegenJobItem = {
  job_id: string;
  module_id?: string;
  module_title?: string;
  submodule_id?: string;
  submodule_title?: string;
  target_questions?: number;
  created_at?: string;
  status?: string;
  stage?: string;
  stage_at?: string;
  detail?: string;
  queue?: string;
  error_code?: string;
  error_hint?: string;
  error_message?: string;
  error?: string | null;
};

export type UserModuleProgress = {
  module_id: string;
  title: string;
  total: number;
  passed: number;
  percent: number;
  completed: boolean;
};

export type UserHistoryItem = {
  id: string;
  event_type: string;
  created_at: string;
  meta: any;
};

export type UserHistoryDetailedItem = {
  id: string;
  created_at: string;
  kind: string;
  title: string;
  subtitle?: string | null;
  href?: string | null;
  event_type?: string | null;
  ref_id?: string | null;
  meta?: string | null;
  module_id?: string | null;
  module_title?: string | null;
  submodule_id?: string | null;
  submodule_title?: string | null;
  asset_id?: string | null;
  asset_name?: string | null;
};

export type UserDetail = {
  id: string;
  name: string;
  email: string | null;
  role: string;
  position: string | null;
  phone: string | null;
  xp: number;
  level: number;
  streak: number;
  must_change_password: boolean;
  stats: {
    assignments_total: number;
    assignments_completed: number;
    attempts_total: number;
    attempts_passed: number;
    events_total: number;
  };
  modules_progress: {
    completed: UserModuleProgress[];
    in_progress: UserModuleProgress[];
  };
  history: UserHistoryItem[];
};

export type AdminModuleItem = {
  id: string;
  title: string;
  is_active: boolean;
  final_quiz_id?: string | null;
  category?: string | null;
  difficulty?: number | null;
  import_object_key?: string | null;
  storage_prefix?: string | null;
  storage_ok?: boolean;
  question_quality?: {
    total_current: number;
    needs_regen_current: number;
    fallback_current: number;
    ai_current: number;
    heur_current: number;
  };
};

export type AdminSubmoduleItem = {
  id: string;
  module_id: string;
  title: string;
  order: number;
  quiz_id: string;
  requires_quiz?: boolean;
};

export type AdminSubmoduleQualityItem = {
  submodule_id: string;
  order: number;
  title: string;
  quiz_id: string | null;
  total: number;
  needs_regen: number;
  fallback: number;
  ai: number;
  heur: number;
  ok: boolean;
};

export type AdminQuestionItem = {
  id: string;
  quiz_id: string;
  type: string;
  difficulty: number;
  prompt: string;
  correct_answer: string;
  explanation?: string | null;
  concept_tag?: string | null;
  variant_group?: string | null;
};

export type UserItem = {
  id: string;
  name: string;
  role: string;
  position?: string | null;
  xp?: number;
  level?: number;
  streak?: number;
  last_activity_at?: string | null;
  created_at?: string | null;
  progress_summary?: {
    completed_count?: number;
    in_progress_count?: number;
    current?: { module_id: string; title: string; total: number; passed: number; percent: number } | null;
  };
};

export type Module = { id: string; title: string };

export type StorageObjectItem = {
  key: string;
  size?: number;
  last_modified?: any;
  etag?: string;
};
