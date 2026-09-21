/**
 * Клиент к бэкенду.
 *
 * Каждый запрос несёт `Authorization: tma <initData>` — подписанную телеграмом
 * строку. Бэкенд проверяет её HMAC-ключом от BOT_TOKEN, так что подделать
 * личность нельзя. Вне телеграма (разработка) уходит `dev <user_id>`,
 * который бэкенд принимает только при DEV_MODE=true.
 */

import { initData } from "./telegram";
import type {
  AppSettings,
  Keyword,
  KeywordTestResult,
  Lead,
  LeadEvent,
  LeadPage,
  LeadStatus,
  LeadUpdate,
  Me,
  Source,
  Stats,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE || "/api";
const DEV_USER_ID = import.meta.env.VITE_DEV_USER_ID;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

function authHeader(): string | null {
  const signature = initData();
  if (signature) return `tma ${signature}`;
  if (DEV_USER_ID) return `dev ${DEV_USER_ID}`;
  return null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const auth = authHeader();
  if (!auth) {
    throw new ApiError(401, "Открой приложение через бота — вне Telegram нет подписи входа.");
  }

  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: auth,
      ...(init?.headers ?? {}),
    },
  });

  if (response.status === 204) return undefined as T;

  if (!response.ok) {
    let detail = `Ошибка ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail)) detail = body.detail[0]?.msg ?? detail;
    } catch {
      /* тело может быть не json */
    }
    throw new ApiError(response.status, detail);
  }

  return (await response.json()) as T;
}

const qs = (params: Record<string, string | number | undefined | null>): string => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const str = search.toString();
  return str ? `?${str}` : "";
};

export const api = {
  me: () => request<Me>("/me"),

  leads: (params: {
    status?: LeadStatus;
    min_score?: number;
    q?: string;
    source_id?: number;
    with_contact?: boolean;
    limit?: number;
    offset?: number;
  }) =>
    request<LeadPage>(
      `/leads${qs({ ...params, with_contact: params.with_contact ? "true" : undefined })}`,
    ),

  lead: (id: number) => request<Lead>(`/leads/${id}`),

  updateLead: (id: number, patch: LeadUpdate) =>
    request<Lead>(`/leads/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),

  draft: (id: number, extra?: string, regenerate = true) =>
    request<{ draft_message: string }>(`/leads/${id}/draft`, {
      method: "POST",
      body: JSON.stringify({ extra: extra || null, regenerate }),
    }),

  events: (id: number) => request<LeadEvent[]>(`/leads/${id}/events`),

  sources: () => request<Source[]>("/sources"),
  addChannel: (username: string) =>
    request<Source>("/sources", { method: "POST", body: JSON.stringify({ username }) }),
  deleteSource: (id: number) => request<void>(`/sources/${id}`, { method: "DELETE" }),
  updateSource: (id: number, patch: { enabled?: boolean; notes?: string }) =>
    request<Source>(`/sources/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),

  keywords: () => request<Keyword[]>("/keywords"),
  createKeyword: (data: { pattern: string; is_regex: boolean; is_stop: boolean; weight: number }) =>
    request<Keyword>("/keywords", { method: "POST", body: JSON.stringify(data) }),
  updateKeyword: (id: number, patch: Partial<Keyword>) =>
    request<Keyword>(`/keywords/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteKeyword: (id: number) => request<void>(`/keywords/${id}`, { method: "DELETE" }),
  testKeywords: (text: string) =>
    request<KeywordTestResult>("/keywords/test", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  settings: () => request<AppSettings>("/settings"),
  saveSettings: (values: Partial<AppSettings>) =>
    request<AppSettings>("/settings", { method: "PUT", body: JSON.stringify({ values }) }),

  stats: () => request<Stats>("/stats/overview"),
};
