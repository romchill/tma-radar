/**
 * Тонкая обёртка над window.Telegram.WebApp.
 *
 * Namespace от телеграма приходит из скрипта в index.html, поэтому всё здесь
 * защищено от его отсутствия: приложение должно открываться и в обычном
 * браузере (для разработки), просто без хаптики и системных кнопок.
 */

type BackButton = {
  show(): void;
  hide(): void;
  onClick(cb: () => void): void;
  offClick(cb: () => void): void;
};

type HapticFeedback = {
  impactOccurred(style: "light" | "medium" | "heavy" | "rigid" | "soft"): void;
  notificationOccurred(type: "error" | "success" | "warning"): void;
  selectionChanged(): void;
};

type WebApp = {
  initData: string;
  initDataUnsafe: { user?: { id: number; username?: string; first_name?: string } };
  colorScheme: "light" | "dark";
  themeParams: Record<string, string>;
  BackButton: BackButton;
  HapticFeedback: HapticFeedback;
  ready(): void;
  expand(): void;
  close(): void;
  openTelegramLink(url: string): void;
  openLink(url: string, options?: { try_instant_view?: boolean }): void;
  showConfirm(message: string, cb: (ok: boolean) => void): void;
  showAlert(message: string, cb?: () => void): void;
  setHeaderColor?(color: string): void;
  disableVerticalSwipes?(): void;
  version: string;
};

declare global {
  interface Window {
    Telegram?: { WebApp?: WebApp };
    __launchHash?: string;
  }
}

export const tg = (): WebApp | undefined => window.Telegram?.WebApp;

const INIT_DATA_KEY = "tma_init_data";

/** Параметры запуска, снятые до того, как telegram-web-app.js затёр якорь. */
export function launchParams(): URLSearchParams {
  return new URLSearchParams((window.__launchHash || "").replace(/^#/, ""));
}

/**
 * Подпись входа. Берётся из трёх мест по убыванию надёжности:
 *
 * 1. `WebApp.initData` — обычный путь;
 * 2. якорь адреса — если скрипт Telegram почему-то не разобрал его сам;
 * 3. sessionStorage — Telegram передаёт подпись только при первом открытии
 *    мини-аппа, а при перезагрузке окна её уже нет. Подпись действительна
 *    сутки, поэтому сохранённая вполне рабочая.
 */
export function initData(): string {
  const live = tg()?.initData;
  if (live) {
    try {
      sessionStorage.setItem(INIT_DATA_KEY, live);
    } catch {
      /* приватный режим — переживём */
    }
    return live;
  }

  const fromHash = launchParams().get("tgWebAppData");
  if (fromHash) {
    try {
      sessionStorage.setItem(INIT_DATA_KEY, fromHash);
    } catch {
      /* ignore */
    }
    return fromHash;
  }

  try {
    return sessionStorage.getItem(INIT_DATA_KEY) ?? "";
  } catch {
    return "";
  }
}

/** Запущены ли мы реально внутри Telegram (а не в браузере на localhost). */
export const inTelegram = (): boolean => Boolean(initData());

export function initTelegram(): void {
  const app = tg();
  if (!app) return;
  app.ready();
  app.expand();
  // свайп вниз закрывает мини-апп и мешает скроллу списков
  app.disableVerticalSwipes?.();
}

export function haptic(type: "light" | "medium" | "success" | "error" | "select"): void {
  const h = tg()?.HapticFeedback;
  if (!h) return;
  try {
    if (type === "success" || type === "error") h.notificationOccurred(type);
    else if (type === "select") h.selectionChanged();
    else h.impactOccurred(type);
  } catch {
    /* старые клиенты телеграма умеют не всё */
  }
}

/** Системная кнопка «назад» в шапке телеграма. Возвращает отписку. */
export function bindBackButton(onBack: () => void): () => void {
  const app = tg();
  if (!app) return () => {};
  app.BackButton.onClick(onBack);
  app.BackButton.show();
  return () => {
    app.BackButton.offClick(onBack);
    app.BackButton.hide();
  };
}

/** Открывает диалог с человеком: телеграм — внутри клиента, остальное — браузером. */
export function openContact(url: string | null): void {
  if (!url) return;
  const app = tg();
  if (!app) {
    window.open(url, "_blank");
    return;
  }
  if (url.includes("t.me/")) app.openTelegramLink(url);
  else app.openLink(url);
}

export function openLink(url: string): void {
  const app = tg();
  if (app) app.openLink(url);
  else window.open(url, "_blank");
}

export function confirm(message: string): Promise<boolean> {
  const app = tg();
  if (!app) return Promise.resolve(window.confirm(message));
  return new Promise((resolve) => app.showConfirm(message, resolve));
}

export function alert(message: string): void {
  const app = tg();
  if (app) app.showAlert(message);
  else window.alert(message);
}

/**
 * Копирование в буфер. В вебвью телеграма Clipboard API доступен не всегда,
 * поэтому есть фолбэк через скрытый textarea + execCommand.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(area);
      return ok;
    } catch {
      return false;
    }
  }
}

/** Разбирает `?startapp=lead_123` — так бот открывает конкретную карточку. */
export function startParamLeadId(): number | null {
  const raw =
    new URLSearchParams(window.location.search).get("startapp") ??
    new URLSearchParams(window.location.search).get("tgWebAppStartParam");
  if (!raw) return null;
  const match = /^lead_(\d+)$/.exec(raw);
  return match ? Number(match[1]) : null;
}
