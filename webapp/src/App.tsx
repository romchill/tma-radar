import { useEffect, useState } from "react";

import { Diagnostics } from "./components/Diagnostics";
import { Feed } from "./components/Feed";
import { Kanban } from "./components/Kanban";
import { LeadDetail } from "./components/LeadDetail";
import { Settings } from "./components/Settings";
import { Stats } from "./components/Stats";
import { Empty, Spinner } from "./components/ui";
import { api, ApiError } from "./lib/api";
import { bindBackButton, initTelegram, startParamLeadId } from "./lib/telegram";
import type { Me } from "./lib/types";

type Tab = "feed" | "kanban" | "stats" | "settings";

const TABS: { value: Tab; icon: string; label: string }[] = [
  { value: "feed", icon: "📡", label: "Лента" },
  { value: "kanban", icon: "🗂", label: "Воронка" },
  { value: "stats", icon: "📊", label: "Аналитика" },
  { value: "settings", icon: "⚙️", label: "Настройки" },
];

export function App() {
  const [tab, setTab] = useState<Tab>("feed");
  // null = список, число = открыта карточка. Отдельный экран поверх вкладок.
  const [openLeadId, setOpenLeadId] = useState<number | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);

  useEffect(() => {
    initTelegram();
    // бот открывает приложение ссылкой ?startapp=lead_123 — сразу на карточку
    const deepLink = startParamLeadId();
    if (deepLink) setOpenLeadId(deepLink);

    api
      .me()
      .then(setMe)
      .catch((err) =>
        setAuthError(err instanceof ApiError ? err.message : (err as Error).message),
      );
  }, []);

  // системная кнопка «назад» в шапке телеграма закрывает карточку
  useEffect(() => {
    if (openLeadId === null) return;
    return bindBackButton(() => setOpenLeadId(null));
  }, [openLeadId]);

  if (authError) {
    return (
      <div className="screen">
        <Empty icon="🔒" title="Нет доступа" hint={authError} />
        <Diagnostics />
      </div>
    );
  }

  if (!me) return <Spinner />;

  return (
    <>
      {openLeadId !== null ? (
        <LeadDetail
          key={openLeadId}
          leadId={openLeadId}
          aiEnabled={me.ai_enabled}
          onClose={() => setOpenLeadId(null)}
        />
      ) : (
        <>
          {tab === "feed" && <Feed onOpenLead={setOpenLeadId} />}
          {tab === "kanban" && <Kanban onOpenLead={setOpenLeadId} />}
          {tab === "stats" && <Stats />}
          {tab === "settings" && <Settings />}
        </>
      )}

      {openLeadId === null && (
        <nav className="tabbar">
          {TABS.map((item) => (
            <button
              key={item.value}
              className={tab === item.value ? "active" : ""}
              onClick={() => setTab(item.value)}
            >
              <span className="icon">{item.icon}</span>
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
      )}
    </>
  );
}
