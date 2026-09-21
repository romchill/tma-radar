/** Зеркало pydantic-схем бэкенда (backend/app/schemas.py). */

export type LeadStatus =
  | "new"
  | "contacted"
  | "dialog"
  | "offer"
  | "deal"
  | "lost"
  | "trash";

export const PIPELINE: LeadStatus[] = ["new", "contacted", "dialog", "offer", "deal"];

export const STATUS_LABEL: Record<LeadStatus, string> = {
  new: "Новые",
  contacted: "Написал",
  dialog: "Диалог",
  offer: "Оффер",
  deal: "Сделка",
  lost: "Слив",
  trash: "Мусор",
};

export type Lead = {
  id: number;
  score: number;
  niche: string | null;
  budget_hint: string | null;
  urgency: "low" | "medium" | "high" | null;
  pain: string | null;
  summary: string | null;
  why: string | null;
  status: LeadStatus;
  draft_message: string | null;
  notes: string | null;
  deal_amount: number | null;
  created_at: string;
  contacted_at: string | null;
  next_followup_at: string | null;

  // из raw_message
  text: string;
  link: string | null;
  chat_title: string | null;
  author_id: number | null;
  author_username: string | null;
  author_name: string | null;
  /** готовая ссылка «написать»: t.me или vk.com; null — контакта нет */
  contact_url: string | null;
  matched: string[];
  posted_at: string | null;
};

export type LeadPage = {
  items: Lead[];
  total: number;
  limit: number;
  offset: number;
};

export type LeadUpdate = Partial<{
  status: LeadStatus;
  notes: string;
  draft_message: string;
  deal_amount: number | null;
  next_followup_at: string | null;
}>;

export type LeadEvent = {
  id: number;
  kind: string;
  payload: Record<string, unknown> | null;
  created_at: string;
};

export type Source = {
  id: number;
  kind: string;
  tg_chat_id: number | null;
  username: string | null;
  title: string | null;
  enabled: boolean;
  notes: string | null;
  /** дата свежайшего поста; по ней видно, что источник умер */
  last_post_at: string | null;
  leads_count: number;
  raw_count: number;
};

export type Keyword = {
  id: number;
  pattern: string;
  is_regex: boolean;
  /** стоп-слово: сработало — пост отбрасывается целиком */
  is_stop: boolean;
  weight: number;
  enabled: boolean;
};

export type KeywordTestResult = {
  matched: string[];
  weight: number;
  blocked_by: string | null;
};

export type AppSettings = {
  scorer_system: string;
  writer_system: string;
  writer_extra: string;
  score_threshold: number;
  score_hot: number;
  daily_lead_cap: number;
  contact_cooldown_days: number;
};

export type Stats = {
  by_status: Partial<Record<LeadStatus, number>>;
  leads_today: number;
  leads_7d: number;
  raw_by_status: Record<string, number>;
  hot_open: number;
  followups_due: number;
  avg_score: number;
  top_sources: { title: string; leads: number; deals: number }[];
  top_keywords: { pattern: string; leads: number }[];
};

export type Me = {
  id: number;
  username: string | null;
  title: string;
  is_admin: boolean;
  /** есть ли ключ Anthropic; без него черновики собираются по шаблону */
  ai_enabled: boolean;
};
