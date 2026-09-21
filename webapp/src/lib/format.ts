import type { Lead } from "./types";

export function scoreClass(score: number): string {
  if (score >= 85) return "hot";
  if (score >= 70) return "warm";
  if (score >= 60) return "cool";
  return "cold";
}

const UNITS: [number, string, string, string][] = [
  [60, "мин", "мин", "мин"],
  [24, "ч", "ч", "ч"],
  [7, "д", "д", "д"],
];

export function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "только что";
  if (diff < 3600) return `${Math.floor(diff / 60)} ${UNITS[0][1]} назад`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} ${UNITS[1][1]} назад`;
  const days = Math.floor(diff / 86400);
  if (days < 30) return `${days} ${UNITS[2][1]} назад`;
  return new Date(iso).toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
}

export function leadAuthor(lead: Lead): string {
  return (
    lead.author_name ||
    (lead.author_username ? `@${lead.author_username}` : null) ||
    "аноним"
  );
}

export const URGENCY_MARK: Record<string, string> = {
  high: "🔥",
  medium: "⚡",
  low: "",
};

/** ISO-строка для next_followup_at через N дней от текущего момента. */
export function inDays(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date.toISOString();
}

export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}
