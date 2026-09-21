import { useEffect, useState } from "react";

import { api } from "../lib/api";
import { confirm, haptic } from "../lib/telegram";

/** Источник, молчащий больше месяца, скорее всего мёртв — это надо видеть. */
function sourceAge(iso: string): JSX.Element {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (days > 30) {
    return <span style={{ color: "var(--danger)" }}>молчит {days} дн — мёртвый</span>;
  }
  if (days > 7) return <>молчит {days} дн</>;
  return <>свежий</>;
}
import type { AppSettings, Keyword, KeywordTestResult, Source } from "../lib/types";
import { Chips, Empty, ErrorBanner, Field, Spinner, Switch } from "./ui";

type Tab = "sources" | "keywords" | "limits" | "prompts";

const TABS: { value: Tab; label: string }[] = [
  { value: "sources", label: "Источники" },
  { value: "keywords", label: "Ключевики" },
  { value: "limits", label: "Пороги" },
  { value: "prompts", label: "Промпты" },
];

/* ------------------------------------------------------------ источники */

function Sources() {
  const [sources, setSources] = useState<Source[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [channel, setChannel] = useState("");
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    api
      .sources()
      .then(setSources)
      .catch((err) => setError((err as Error).message))
      .finally(() => setLoading(false));
  }, []);

  const add = async () => {
    if (!channel.trim()) return;
    setAdding(true);
    setError(null);
    try {
      const created = await api.addChannel(channel.trim());
      setSources((prev) => [created, ...prev.filter((item) => item.id !== created.id)]);
      setChannel("");
      haptic("success");
    } catch (err) {
      setError((err as Error).message);
      haptic("error");
    } finally {
      setAdding(false);
    }
  };

  const remove = async (source: Source) => {
    if (!(await confirm(`Убрать ${source.title || source.username} из сбора?`))) return;
    const before = sources;
    setSources((prev) => prev.filter((item) => item.id !== source.id));
    try {
      await api.deleteSource(source.id);
    } catch (err) {
      setError((err as Error).message);
      setSources(before);
    }
  };

  const toggle = async (source: Source) => {
    haptic("select");
    const next = !source.enabled;
    setSources((prev) =>
      prev.map((item) => (item.id === source.id ? { ...item, enabled: next } : item)),
    );
    try {
      await api.updateSource(source.id, { enabled: next });
    } catch (err) {
      setError((err as Error).message);
      setSources((prev) =>
        prev.map((item) => (item.id === source.id ? { ...item, enabled: !next } : item)),
      );
    }
  };

  if (loading) return <Spinner />;

  return (
    <>
      {error && <ErrorBanner error={error} />}

      <div className="card">
        <div className="section-title" style={{ padding: 0 }}>
          Добавить канал
        </div>
        <input
          placeholder="@канал в телеграме или vk.com/группа"
          value={channel}
          onChange={(event) => setChannel(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && void add()}
        />
        <button className="btn" onClick={() => void add()} disabled={adding || !channel.trim()}>
          {adding ? "Проверяю канал…" : "Добавить"}
        </button>
        <div className="hint">
          <b>ВК даёт прямой контакт</b> — на стене группы пишут сами люди, им можно
          написать сразу. Телеграм-каналы чаще перепечатывают биржи, там контакта
          нет. Чаты телеграма не читаются: у них нет веб-версии.
        </div>
      </div>

      {sources.length === 0 ? (
        <Empty
          icon="📡"
          title="Источников пока нет"
          hint="Добавь канал телеграма или группу ВК — радар начнёт читать раз в 5 минут."
        />
      ) : (
        <div className="card">
          {sources.map((source, index) => (
            <div
              key={source.id}
              className="row"
              style={{ borderTop: index ? "1px solid var(--separator)" : "none", paddingTop: index ? 10 : 0 }}
            >
              <div style={{ minWidth: 0, flex: 1 }}>
                <div
                  style={{
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {source.title || source.username || source.tg_chat_id}
                </div>
                <div className="hint" style={{ fontSize: 12 }}>
                  {source.leads_count} лидов из {source.raw_count} пойманных
                  {source.last_post_at && <> · {sourceAge(source.last_post_at)}</>}
                </div>
              </div>
              <Switch on={source.enabled} onToggle={() => void toggle(source)} />
              <button className="btn danger small" onClick={() => void remove(source)}>
                ✕
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------ ключевики */

function Keywords() {
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [pattern, setPattern] = useState("");
  const [isRegex, setIsRegex] = useState(false);
  const [isStop, setIsStop] = useState(false);

  const [sample, setSample] = useState("");
  const [testResult, setTestResult] = useState<KeywordTestResult | null>(null);

  const load = () => {
    api
      .keywords()
      .then(setKeywords)
      .catch((err) => setError((err as Error).message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const add = async () => {
    if (!pattern.trim()) return;
    setError(null);
    try {
      const created = await api.createKeyword({
        pattern: pattern.trim(),
        is_regex: isRegex,
        is_stop: isStop,
        weight: isStop ? 0 : 20,
      });
      setKeywords((prev) => [created, ...prev]);
      setPattern("");
      haptic("success");
    } catch (err) {
      setError((err as Error).message);
      haptic("error");
    }
  };

  const toggle = async (keyword: Keyword) => {
    haptic("select");
    const next = !keyword.enabled;
    setKeywords((prev) =>
      prev.map((item) => (item.id === keyword.id ? { ...item, enabled: next } : item)),
    );
    try {
      await api.updateKeyword(keyword.id, { enabled: next });
    } catch (err) {
      setError((err as Error).message);
      load();
    }
  };

  const remove = async (keyword: Keyword) => {
    setKeywords((prev) => prev.filter((item) => item.id !== keyword.id));
    try {
      await api.deleteKeyword(keyword.id);
    } catch (err) {
      setError((err as Error).message);
      load();
    }
  };

  const test = async () => {
    if (!sample.trim()) return;
    try {
      setTestResult(await api.testKeywords(sample));
      haptic("light");
    } catch (err) {
      setError((err as Error).message);
    }
  };

  if (loading) return <Spinner />;

  return (
    <>
      {error && <ErrorBanner error={error} />}

      <div className="card">
        <div className="section-title" style={{ padding: 0 }}>
          Добавить
        </div>
        <input
          placeholder={isRegex ? "regex, напр. (нужен|ищу)\\s+бот" : "подстрока, напр. мини апп"}
          value={pattern}
          onChange={(event) => setPattern(event.target.value)}
        />
        <div className="row between">
          <span className="hint">Регулярное выражение</span>
          <Switch on={isRegex} onToggle={() => setIsRegex((value) => !value)} />
        </div>
        <div className="row between">
          <span className="hint">Стоп-слово (отбрасывать такие посты)</span>
          <Switch on={isStop} onToggle={() => setIsStop((value) => !value)} />
        </div>
        <button className="btn" onClick={() => void add()} disabled={!pattern.trim()}>
          Добавить
        </button>
      </div>

      <div className="card">
        <div className="section-title" style={{ padding: 0 }}>
          Песочница
        </div>
        <div className="hint" style={{ marginTop: -4 }}>
          Прогоняет текст через текущий набор, ничего не сохраняя.
        </div>
        <textarea
          placeholder="Вставь реальное сообщение из чата"
          value={sample}
          onChange={(event) => setSample(event.target.value)}
          style={{ minHeight: 70 }}
        />
        <button className="btn secondary small" onClick={() => void test()} disabled={!sample.trim()}>
          Проверить
        </button>
        {testResult && (
          <div className={testResult.blocked_by ? "" : testResult.matched.length ? "" : "hint"}>
            {testResult.blocked_by ? (
              <span style={{ color: "var(--danger)" }}>
                Отброшено стоп-словом — такой пост в ленту не попадёт.
              </span>
            ) : testResult.matched.length ? (
              `Сработало ${testResult.matched.length}, вес ${testResult.weight} — пост ушёл бы на оценку.`
            ) : (
              "Ни один ключевик не сработал — такой пост радар пропустит."
            )}
            <div>
              {testResult.blocked_by && <span className="tag">{testResult.blocked_by}</span>}
              {!testResult.blocked_by &&
                testResult.matched.map((item) => (
                  <span className="tag" key={item}>
                    {item}
                  </span>
                ))}
            </div>
          </div>
        )}
      </div>

      <KeywordList
        title={`Ловят заказы (${keywords.filter((k) => !k.is_stop && k.enabled).length})`}
        items={keywords.filter((k) => !k.is_stop)}
        onToggle={toggle}
        onRemove={remove}
      />
      <KeywordList
        title={`Стоп-слова (${keywords.filter((k) => k.is_stop && k.enabled).length})`}
        hint="Сработало любое — пост отбрасывается, сколько бы ключевиков ни совпало."
        items={keywords.filter((k) => k.is_stop)}
        onToggle={toggle}
        onRemove={remove}
      />
    </>
  );
}

function KeywordList({
  title,
  hint,
  items,
  onToggle,
  onRemove,
}: {
  title: string;
  hint?: string;
  items: Keyword[];
  onToggle: (k: Keyword) => Promise<void>;
  onRemove: (k: Keyword) => Promise<void>;
}) {
  if (items.length === 0) return null;
  return (
      <div className="card">
        <div className="section-title" style={{ padding: 0 }}>
          {title}
        </div>
        {hint && <div className="hint" style={{ marginTop: -4 }}>{hint}</div>}
        {items.map((keyword, index) => (
          <div
            key={keyword.id}
            className="row"
            style={{ borderTop: index ? "1px solid var(--separator)" : "none", paddingTop: index ? 10 : 0 }}
          >
            <div style={{ minWidth: 0, flex: 1 }}>
              <div
                style={{
                  fontFamily: "ui-monospace, monospace",
                  fontSize: 12,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {keyword.pattern}
              </div>
              <div className="hint" style={{ fontSize: 11 }}>
                {keyword.is_regex ? "regex" : "подстрока"}
                {!keyword.is_stop && ` · вес ${keyword.weight}`}
              </div>
            </div>
            <Switch on={keyword.enabled} onToggle={() => void onToggle(keyword)} />
            <button className="btn danger small" onClick={() => void onRemove(keyword)}>
              ✕
            </button>
          </div>
        ))}
      </div>
  );
}

/* ------------------------------------------------------------ пороги и промпты */

function SettingsForm({ tab }: { tab: "limits" | "prompts" }) {
  const [values, setValues] = useState<AppSettings | null>(null);
  const [saved, setSaved] = useState<AppSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .settings()
      .then((data) => {
        setValues(data);
        setSaved(data);
      })
      .catch((err) => setError((err as Error).message))
      .finally(() => setLoading(false));
  }, []);

  const save = async () => {
    if (!values) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await api.saveSettings(values);
      setValues(updated);
      setSaved(updated);
      haptic("success");
    } catch (err) {
      setError((err as Error).message);
      haptic("error");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Spinner />;
  if (!values) return <ErrorBanner error={error ?? "Не загрузилось"} />;

  const dirty = JSON.stringify(values) !== JSON.stringify(saved);
  const set = <K extends keyof AppSettings>(key: K, value: AppSettings[K]) =>
    setValues({ ...values, [key]: value });

  return (
    <>
      {error && <ErrorBanner error={error} />}

      {tab === "limits" ? (
        <div className="card">
          <Field label="Порог попадания в ленту (score)">
            <input
              type="number"
              value={values.score_threshold}
              onChange={(event) => set("score_threshold", Number(event.target.value))}
            />
          </Field>
          <Field label="Порог мгновенного пуша (score)">
            <input
              type="number"
              value={values.score_hot}
              onChange={(event) => set("score_hot", Number(event.target.value))}
            />
          </Field>
          <Field label="Уведомлений в телеграм за сутки, 0 = без лимита">
            <input
              type="number"
              value={values.daily_lead_cap}
              onChange={(event) => set("daily_lead_cap", Number(event.target.value))}
            />
          </Field>
          <div className="hint" style={{ marginTop: -4 }}>
            Каждый заказ прилетает пушем сразу. Когда за сутки наберётся N
            уведомлений, бот замолкает до утра, но лента продолжает пополняться.
          </div>
          <Field label="Не трогать одного автора чаще, чем раз в N дней">
            <input
              type="number"
              value={values.contact_cooldown_days}
              onChange={(event) => set("contact_cooldown_days", Number(event.target.value))}
            />
          </Field>
        </div>
      ) : (
        <>
          <div className="card">
            <Field label="Промпт скоринга">
              <textarea
                value={values.scorer_system}
                onChange={(event) => set("scorer_system", event.target.value)}
                style={{ minHeight: 220, fontSize: 13 }}
              />
            </Field>
            <div className="hint" style={{ marginTop: -4 }}>
              Первые недели правь именно его: смотри мусор в ленте и дописывай,
              что лидом не считать.
            </div>
          </div>

          <div className="card">
            <Field label="Промпт первого сообщения">
              <textarea
                value={values.writer_system}
                onChange={(event) => set("writer_system", event.target.value)}
                style={{ minHeight: 180, fontSize: 13 }}
              />
            </Field>
          </div>

          <div className="card">
            <Field label="Постоянная вводная к черновикам">
              <textarea
                value={values.writer_extra}
                onChange={(event) => set("writer_extra", event.target.value)}
                placeholder="Напр.: работаю один, срок от 2 недель, есть кейсы в онлайн-школах"
                style={{ minHeight: 80 }}
              />
            </Field>
          </div>
        </>
      )}

      <button className="btn" onClick={() => void save()} disabled={!dirty || saving}>
        {saving ? "Сохраняю…" : dirty ? "Сохранить" : "Сохранено"}
      </button>
    </>
  );
}

/* ------------------------------------------------------------ экран */

export function Settings() {
  const [tab, setTab] = useState<Tab>("sources");

  return (
    <div className="screen">
      <Chips options={TABS} value={tab} onChange={setTab} />
      {tab === "sources" && <Sources />}
      {tab === "keywords" && <Keywords />}
      {(tab === "limits" || tab === "prompts") && <SettingsForm key={tab} tab={tab} />}
    </div>
  );
}
