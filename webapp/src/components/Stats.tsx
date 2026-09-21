import { useEffect, useState } from "react";

import { api } from "../lib/api";
import { PIPELINE, STATUS_LABEL } from "../lib/types";
import type { Stats as StatsData } from "../lib/types";
import { ErrorBanner, Spinner } from "./ui";

function Metric({ value, label }: { value: number | string; label: string }) {
  return (
    <div style={{ flex: 1, textAlign: "center" }}>
      <div className="strong" style={{ fontSize: 24 }}>
        {value}
      </div>
      <div className="hint" style={{ fontSize: 12 }}>
        {label}
      </div>
    </div>
  );
}

export function Stats() {
  const [data, setData] = useState<StatsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    api
      .stats()
      .then(setData)
      .catch((err) => setError((err as Error).message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  if (loading) return <Spinner />;
  if (!data) {
    return (
      <div className="screen">
        <ErrorBanner error={error ?? "Не загрузилось"} onRetry={load} />
      </div>
    );
  }

  const funnelMax = Math.max(1, ...PIPELINE.map((status) => data.by_status[status] ?? 0));
  const contacted =
    (data.by_status.contacted ?? 0) +
    (data.by_status.dialog ?? 0) +
    (data.by_status.offer ?? 0) +
    (data.by_status.deal ?? 0);
  const deals = data.by_status.deal ?? 0;
  const conversion = contacted > 0 ? Math.round((deals / contacted) * 100) : 0;

  return (
    <div className="screen">
      {error && <ErrorBanner error={error} onRetry={load} />}

      <div className="card">
        <div className="row">
          <Metric value={data.leads_today} label="за сутки" />
          <Metric value={data.leads_7d} label="за неделю" />
          <Metric value={data.avg_score} label="ср. score" />
        </div>
        {(data.hot_open > 0 || data.followups_due > 0) && (
          <>
            <div className="divider" />
            <div className="row">
              <Metric value={data.hot_open} label="горячих ждут" />
              <Metric value={data.followups_due} label="напомнить" />
              <Metric value={`${conversion}%`} label="написал → сделка" />
            </div>
          </>
        )}
      </div>

      <div className="card">
        <div className="section-title" style={{ padding: 0 }}>
          Воронка
        </div>
        {PIPELINE.map((status) => {
          const count = data.by_status[status] ?? 0;
          return (
            <div key={status} className="row" style={{ gap: 8 }}>
              <div style={{ width: 76, fontSize: 13 }}>{STATUS_LABEL[status]}</div>
              <div style={{ flex: 1 }}>
                <div className="bar" style={{ width: `${(count / funnelMax) * 100}%` }} />
              </div>
              <div className="hint" style={{ width: 28, textAlign: "right" }}>
                {count}
              </div>
            </div>
          );
        })}
      </div>

      <div className="card">
        <div className="section-title" style={{ padding: 0 }}>
          Очередь скоринга
        </div>
        <div className="row between hint">
          <span>ждут оценки</span>
          <span>{data.raw_by_status.pending ?? 0}</span>
        </div>
        <div className="row between hint">
          <span>оценено</span>
          <span>{data.raw_by_status.scored ?? 0}</span>
        </div>
        <div className="row between hint">
          <span>отсеяно моделью</span>
          <span>{data.raw_by_status.rejected ?? 0}</span>
        </div>
        <div className="row between hint">
          <span>дубли по кулдауну</span>
          <span>{data.raw_by_status.duplicate ?? 0}</span>
        </div>
        {(data.raw_by_status.error ?? 0) > 0 && (
          <div className="row between" style={{ color: "var(--danger)" }}>
            <span>ошибки</span>
            <span>{data.raw_by_status.error}</span>
          </div>
        )}
      </div>

      {data.top_sources.length > 0 && (
        <div className="card">
          <div className="section-title" style={{ padding: 0 }}>
            Источники по лидам
          </div>
          {data.top_sources.map((source) => (
            <div className="row between" key={source.title}>
              <span
                style={{
                  minWidth: 0,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {source.title}
              </span>
              <span className="hint">
                {source.leads}
                {source.deals > 0 && ` · ${source.deals} сделок`}
              </span>
            </div>
          ))}
        </div>
      )}

      {data.top_keywords.length > 0 && (
        <div className="card">
          <div className="section-title" style={{ padding: 0 }}>
            Ключевики, которые приносят лидов
          </div>
          <div className="hint" style={{ marginTop: -4 }}>
            То, чего нет в этом списке, тащит только шум — можно выключать.
          </div>
          {data.top_keywords.map((keyword) => (
            <div className="row between" key={keyword.pattern}>
              <span
                style={{
                  minWidth: 0,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  fontFamily: "ui-monospace, monospace",
                  fontSize: 12,
                }}
              >
                {keyword.pattern}
              </span>
              <span className="hint">{keyword.leads}</span>
            </div>
          ))}
        </div>
      )}

      <button className="btn secondary" onClick={load}>
        Обновить
      </button>
    </div>
  );
}
