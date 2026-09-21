import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import { leadAuthor, scoreClass, timeAgo, URGENCY_MARK } from "../lib/format";
import { haptic } from "../lib/telegram";
import type { Lead, LeadStatus } from "../lib/types";
import { Chips, Empty, ErrorBanner, Spinner } from "./ui";

type Filter = "all" | "writable" | "hot" | "trash";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "Все новые" },
  // перепечатки бирж контакта не дают — этот фильтр оставляет тех,
  // кому можно написать в телеграм прямо сейчас
  { value: "writable", label: "✍️ Можно написать" },
  { value: "hot", label: "🔥 Горячие" },
  { value: "trash", label: "Мусор" },
];

const PAGE = 30;

/** Карточка в списке. Тап — открыть, кнопки — быстрые действия без открытия. */
function LeadRow({
  lead,
  onOpen,
  onQuick,
}: {
  lead: Lead;
  onOpen: () => void;
  onQuick: (status: LeadStatus) => void;
}) {
  return (
    <div className="card" onClick={onOpen}>
      <div className="row">
        <div className={`score ${scoreClass(lead.score)}`}>{lead.score}</div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="strong" style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
            {URGENCY_MARK[lead.urgency ?? "low"]} {lead.niche || "ниша неясна"}
          </div>
          <div className="hint" style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
            {leadAuthor(lead)} · {lead.chat_title || "?"} · {timeAgo(lead.posted_at ?? lead.created_at)}
          </div>
        </div>
      </div>

      <div className="wrap clamp-3">{lead.summary || lead.text}</div>

      {lead.budget_hint && <div className="hint">💰 {lead.budget_hint}</div>}

      {lead.status === "new" && (
        <div className="btn-row" onClick={(event) => event.stopPropagation()}>
          <button className="btn secondary small" onClick={() => onQuick("trash")}>
            В мусор
          </button>
          <button className="btn small" onClick={onOpen}>
            Открыть
          </button>
        </div>
      )}
    </div>
  );
}

export function Feed({ onOpenLead }: { onOpenLead: (id: number) => void }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [leads, setLeads] = useState<Lead[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // защита от гонки: применяем ответ, только если запрос всё ещё актуален
  const requestId = useRef(0);

  const load = useCallback(
    async (offset = 0) => {
      const current = ++requestId.current;
      if (offset === 0) setLoading(true);
      setError(null);
      try {
        const page = await api.leads({
          status: filter === "trash" ? "trash" : "new",
          min_score: filter === "hot" ? 85 : undefined,
          with_contact: filter === "writable" || undefined,
          q: query.trim() || undefined,
          limit: PAGE,
          offset,
        });
        if (current !== requestId.current) return;
        setLeads((prev) => (offset === 0 ? page.items : [...prev, ...page.items]));
        setTotal(page.total);
      } catch (err) {
        if (current === requestId.current) setError((err as Error).message);
      } finally {
        if (current === requestId.current) setLoading(false);
      }
    },
    [filter, query],
  );

  useEffect(() => {
    const timer = setTimeout(() => void load(0), query ? 350 : 0);
    return () => clearTimeout(timer);
  }, [load, query]);

  const quickAction = async (lead: Lead, status: LeadStatus) => {
    haptic("light");
    setLeads((prev) => prev.filter((item) => item.id !== lead.id));
    setTotal((value) => Math.max(0, value - 1));
    try {
      await api.updateLead(lead.id, { status });
    } catch (err) {
      setError((err as Error).message);
      void load(0);
    }
  };

  return (
    <div className="screen">
      <Chips options={FILTERS} value={filter} onChange={setFilter} />

      <input
        placeholder="Поиск по тексту, нише, чату"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />

      {error && <ErrorBanner error={error} onRetry={() => void load(0)} />}

      {loading && leads.length === 0 ? (
        <Spinner />
      ) : leads.length === 0 ? (
        <Empty
          icon={filter === "trash" ? "🗑" : "📡"}
          title={filter === "trash" ? "Мусора нет" : "Пока пусто"}
          hint={
            filter === "trash"
              ? "Сюда попадает то, что не набрало порога или что ты убрал сам"
              : filter === "writable"
                ? "Пока нет лидов с прямым контактом. Они приходят из чатов, куда добавлен бот — каналы-биржи контакта не дают."
                : "Радар слушает источники. Как появится лид — он будет здесь и придёт пушем."
          }
        />
      ) : (
        <div className="list">
          {leads.map((lead) => (
            <LeadRow
              key={lead.id}
              lead={lead}
              onOpen={() => onOpenLead(lead.id)}
              onQuick={(status) => void quickAction(lead, status)}
            />
          ))}

          {leads.length < total && (
            <button
              className="btn secondary"
              disabled={loading}
              onClick={() => void load(leads.length)}
            >
              {loading ? "Загружаю…" : `Показать ещё (${total - leads.length})`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
