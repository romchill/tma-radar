import { useEffect, useState } from "react";

import { api } from "../lib/api";
import { leadAuthor, scoreClass, timeAgo } from "../lib/format";
import { PIPELINE, STATUS_LABEL } from "../lib/types";
import type { Lead, LeadStatus } from "../lib/types";
import { Empty, ErrorBanner, Spinner } from "./ui";

/**
 * Канбан без drag-n-drop: в мини-аппе перетаскивание конфликтует со свайпами
 * телеграма и на телефоне работает хуже, чем тап по стрелке.
 */
export function Kanban({ onOpenLead }: { onOpenLead: (id: number) => void }) {
  const [columns, setColumns] = useState<Record<string, Lead[]>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const pages = await Promise.all(
        PIPELINE.map((status) => api.leads({ status, limit: 50 })),
      );
      const next: Record<string, Lead[]> = {};
      PIPELINE.forEach((status, index) => {
        next[status] = pages[index].items;
      });
      setColumns(next);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const move = async (lead: Lead, direction: 1 | -1) => {
    const index = PIPELINE.indexOf(lead.status);
    const target = PIPELINE[index + direction];
    if (!target) return;

    // оптимистично двигаем, при ошибке перезагружаем правду с сервера
    setColumns((prev) => ({
      ...prev,
      [lead.status]: (prev[lead.status] ?? []).filter((item) => item.id !== lead.id),
      [target]: [{ ...lead, status: target as LeadStatus }, ...(prev[target] ?? [])],
    }));

    try {
      await api.updateLead(lead.id, { status: target as LeadStatus });
    } catch (err) {
      setError((err as Error).message);
      void load();
    }
  };

  if (loading) return <Spinner />;

  const isEmpty = PIPELINE.every((status) => (columns[status] ?? []).length === 0);

  return (
    <div className="screen">
      {error && <ErrorBanner error={error} onRetry={() => void load()} />}

      {isEmpty ? (
        <Empty icon="🗂" title="Воронка пустая" hint="Возьми лид из ленты — он появится здесь." />
      ) : (
        PIPELINE.map((status) => {
          const items = columns[status] ?? [];
          return (
            <div className="kanban-col" key={status}>
              <div className="kanban-head">
                <span>{STATUS_LABEL[status]}</span>
                <span className="hint">{items.length}</span>
              </div>

              {items.length === 0 ? (
                <div className="hint" style={{ paddingBottom: 6 }}>
                  пусто
                </div>
              ) : (
                items.map((lead) => (
                  <div className="mini" key={lead.id}>
                    <div
                      className={`score ${scoreClass(lead.score)}`}
                      style={{ width: 32, height: 32, fontSize: 13, borderRadius: 9 }}
                    >
                      {lead.score}
                    </div>

                    <div
                      style={{ minWidth: 0, flex: 1 }}
                      onClick={() => onOpenLead(lead.id)}
                    >
                      <div
                        className="strong"
                        style={{
                          fontSize: 14,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {lead.niche || leadAuthor(lead)}
                      </div>
                      <div className="hint" style={{ fontSize: 12 }}>
                        {leadAuthor(lead)} · {timeAgo(lead.created_at)}
                      </div>
                    </div>

                    <button
                      className="btn ghost small"
                      onClick={() => void move(lead, -1)}
                      disabled={PIPELINE.indexOf(lead.status) === 0}
                      aria-label="назад по воронке"
                    >
                      ←
                    </button>
                    <button
                      className="btn ghost small"
                      onClick={() => void move(lead, 1)}
                      disabled={PIPELINE.indexOf(lead.status) === PIPELINE.length - 1}
                      aria-label="вперёд по воронке"
                    >
                      →
                    </button>
                  </div>
                ))
              )}
            </div>
          );
        })
      )}
    </div>
  );
}
