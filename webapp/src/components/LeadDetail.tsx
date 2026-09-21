import { useEffect, useState } from "react";

import { api } from "../lib/api";
import { formatDate, inDays, leadAuthor, scoreClass, timeAgo } from "../lib/format";
import { alert, copyText, haptic, openContact, openLink } from "../lib/telegram";
import { PIPELINE, STATUS_LABEL } from "../lib/types";
import type { Lead, LeadEvent } from "../lib/types";
import { Empty, ErrorBanner, Field, Spinner } from "./ui";

const EVENT_LABEL: Record<string, string> = {
  created: "лид заведён",
  status: "смена статуса",
  draft: "сгенерирован черновик",
  capped_out: "вытеснен дневным лимитом",
  followup_fired: "сработало напоминание",
};

export function LeadDetail({
  leadId,
  aiEnabled,
  onClose,
}: {
  leadId: number;
  aiEnabled: boolean;
  onClose: () => void;
}) {
  const [lead, setLead] = useState<Lead | null>(null);
  const [events, setEvents] = useState<LeadEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [draft, setDraft] = useState("");
  const [drafting, setDrafting] = useState(false);
  const [notes, setNotes] = useState("");
  const [savingNotes, setSavingNotes] = useState(false);
  const [fullText, setFullText] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all([api.lead(leadId), api.events(leadId)])
      .then(([leadData, eventList]) => {
        if (!alive) return;
        setLead(leadData);
        setDraft(leadData.draft_message ?? "");
        setNotes(leadData.notes ?? "");
        setEvents(eventList);
      })
      .catch((err) => alive && setError((err as Error).message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [leadId]);

  const patch = async (data: Parameters<typeof api.updateLead>[1]) => {
    if (!lead) return;
    try {
      const updated = await api.updateLead(lead.id, data);
      setLead(updated);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const generate = async () => {
    if (!lead) return;
    setDrafting(true);
    setError(null);
    haptic("light");
    try {
      const result = await api.draft(lead.id);
      setDraft(result.draft_message);
      haptic("success");
    } catch (err) {
      setError((err as Error).message);
      haptic("error");
    } finally {
      setDrafting(false);
    }
  };

  /**
   * Главное действие. Порядок важен:
   * 1) копируем в буфер прямо в обработчике клика — иначе браузер может
   *    не отдать разрешение на clipboard;
   * 2) сохраняем правки черновика и двигаем статус в «написал»;
   * 3) открываем диалог — эта строка закрывает мини-апп, поэтому она последняя.
   */
  const copyAndOpen = async () => {
    if (!lead) return;
    const copied = await copyText(draft);
    if (!copied) {
      alert("Не удалось скопировать. Выдели текст в поле и скопируй вручную.");
      return;
    }
    haptic("success");

    try {
      await api.updateLead(lead.id, {
        draft_message: draft,
        status: lead.status === "new" ? "contacted" : lead.status,
      });
    } catch (err) {
      setError((err as Error).message);
    }

    if (lead.contact_url) {
      openContact(lead.contact_url);
    } else {
      alert(
        "Прямого контакта нет — это перепечатка с биржи. " +
          "Открой оригинал кнопкой «В чате ↗» и откликнись там.",
      );
    }
  };

  const saveNotes = async () => {
    setSavingNotes(true);
    await patch({ notes });
    setSavingNotes(false);
    haptic("light");
  };

  if (loading) return <Spinner />;
  if (!lead) {
    return (
      <div className="screen">
        {error && <ErrorBanner error={error} />}
        <Empty icon="🤷" title="Лид не найден" />
        <button className="btn secondary" onClick={onClose}>
          Назад
        </button>
      </div>
    );
  }

  return (
    <div className="screen">
      {error && <ErrorBanner error={error} />}

      {/* ---------------------------------------------------- шапка */}
      <div className="card">
        <div className="row">
          <div className={`score ${scoreClass(lead.score)}`}>{lead.score}</div>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div className="strong">{lead.niche || "ниша неясна"}</div>
            <div className="hint">
              {leadAuthor(lead)} · {timeAgo(lead.posted_at ?? lead.created_at)}
            </div>
          </div>
        </div>

        {lead.pain && <div className="wrap">{lead.pain}</div>}

        <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
          {lead.budget_hint && <span className="tag">💰 {lead.budget_hint}</span>}
          <span className="tag">{lead.chat_title || "?"}</span>
          {lead.matched.slice(0, 4).map((keyword) => (
            <span className="tag" key={keyword}>
              {keyword}
            </span>
          ))}
        </div>

        {lead.why && <div className="hint">Почему такой score: {lead.why}</div>}
      </div>

      {/* ---------------------------------------------------- исходник */}
      <div className="card">
        <div className="section-title" style={{ padding: 0 }}>
          Исходное сообщение
        </div>
        <div className={`wrap ${fullText ? "" : "clamp-3"}`}>{lead.text}</div>
        <div className="btn-row">
          <button className="btn ghost small" onClick={() => setFullText((value) => !value)}>
            {fullText ? "Свернуть" : "Показать целиком"}
          </button>
          {lead.link && (
            <button className="btn ghost small" onClick={() => openLink(lead.link!)}>
              В чате ↗
            </button>
          )}
        </div>
      </div>

      {/* ---------------------------------------------------- черновик */}
      <div className="card">
        <div className="section-title" style={{ padding: 0 }}>
          Первое сообщение
        </div>

        {draft ? (
          <textarea value={draft} onChange={(event) => setDraft(event.target.value)} />
        ) : (
          <div className="hint">
            {aiEnabled
              ? "Модель напишет черновик под нишу и боль клиента. Перед отправкой можно править."
              : "Черновик соберётся по шаблону под тип заказа. Это не модель — обязательно перечитай и поправь под себя перед отправкой."}
          </div>
        )}

        <div className="btn-row">
          <button className="btn secondary" onClick={() => void generate()} disabled={drafting}>
            {drafting ? "Пишу…" : draft ? "Переписать" : aiEnabled ? "Сгенерировать" : "Собрать по шаблону"}
          </button>
          {draft && (
            <button className="btn" onClick={() => void copyAndOpen()}>
              {lead.contact_url ? "Копировать и открыть" : "Копировать"}
            </button>
          )}
        </div>

        {!lead.contact_url && (
          <div className="hint">
            Прямого контакта нет: пост пришёл с биржи. Откликаться придётся
            в первоисточнике — кнопка «В чате ↗» выше.
          </div>
        )}
      </div>

      {/* ---------------------------------------------------- воронка */}
      <div className="card">
        <div className="section-title" style={{ padding: 0 }}>
          Статус
        </div>
        <div className="chips">
          {PIPELINE.map((status) => (
            <button
              key={status}
              className={`chip ${lead.status === status ? "active" : ""}`}
              onClick={() => void patch({ status })}
            >
              {STATUS_LABEL[status]}
            </button>
          ))}
        </div>
        <div className="btn-row">
          <button className="btn danger small" onClick={() => void patch({ status: "lost" })}>
            Слив
          </button>
          <button className="btn danger small" onClick={() => void patch({ status: "trash" })}>
            В мусор
          </button>
        </div>
      </div>

      {/* ---------------------------------------------------- напоминание */}
      <div className="card">
        <div className="row between">
          <div className="section-title" style={{ padding: 0 }}>
            Напомнить
          </div>
          <div className="hint">{formatDate(lead.next_followup_at)}</div>
        </div>
        <div className="btn-row">
          {[1, 3, 7].map((days) => (
            <button
              key={days}
              className="btn secondary small"
              onClick={() => void patch({ next_followup_at: inDays(days) })}
            >
              +{days} дн
            </button>
          ))}
          {lead.next_followup_at && (
            <button
              className="btn ghost small"
              onClick={() => void patch({ next_followup_at: null })}
            >
              Снять
            </button>
          )}
        </div>
      </div>

      {/* ---------------------------------------------------- заметки */}
      <div className="card">
        <Field label="Заметки">
          <textarea
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            placeholder="Что обсудили, что обещал, когда вернуться"
          />
        </Field>
        <button
          className="btn secondary small"
          onClick={() => void saveNotes()}
          disabled={savingNotes || notes === (lead.notes ?? "")}
        >
          {savingNotes ? "Сохраняю…" : "Сохранить"}
        </button>
      </div>

      {/* ---------------------------------------------------- история */}
      {events.length > 0 && (
        <div className="card">
          <div className="section-title" style={{ padding: 0 }}>
            История
          </div>
          {events.map((event) => (
            <div key={event.id} className="row between hint" style={{ fontSize: 12 }}>
              <span>{EVENT_LABEL[event.kind] ?? event.kind}</span>
              <span>{formatDate(event.created_at)}</span>
            </div>
          ))}
        </div>
      )}

      <button className="btn secondary" onClick={onClose}>
        Назад к ленте
      </button>
    </div>
  );
}
