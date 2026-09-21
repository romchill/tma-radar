import { launchParams, tg } from "../lib/telegram";

/**
 * Показывается только на экране «Нет доступа».
 *
 * Пустой initData бывает по разным причинам, и по одному белому экрану их не
 * различить: приложение может быть открыто ссылкой вместо кнопки, клиент может
 * быть слишком старым, а подпись может теряться при редиректе. Здесь видно,
 * что именно передал Telegram.
 */

function Row({ label, value, bad }: { label: string; value: string; bad?: boolean }) {
  return (
    <div className="row between" style={{ fontSize: 12, gap: 12 }}>
      <span className="hint">{label}</span>
      <span
        style={{
          fontFamily: "ui-monospace, monospace",
          color: bad ? "var(--danger)" : "var(--text)",
          textAlign: "right",
          wordBreak: "break-all",
        }}
      >
        {value}
      </span>
    </div>
  );
}

export function Diagnostics() {
  const app = tg();
  const unsafe = app?.initDataUnsafe;
  const raw = app?.initData ?? "";
  // якорь, снятый до того, как его затёр telegram-web-app.js
  const params = launchParams();
  const keys = [...params.keys()];
  let saved = "";
  try {
    saved = sessionStorage.getItem("tma_init_data") ?? "";
  } catch {
    /* ignore */
  }

  return (
    <div className="card">
      <div className="section-title" style={{ padding: 0 }}>
        Что передал Telegram
      </div>

      <Row label="скрипт Telegram" value={app ? "загружен" : "НЕТ"} bad={!app} />
      <Row label="версия WebApp" value={app?.version ?? "—"} />
      <Row
        label="подпись initData"
        value={raw ? `есть, ${raw.length} симв.` : "ПУСТАЯ"}
        bad={!raw}
      />
      <Row label="пользователь" value={unsafe?.user ? String(unsafe.user.id) : "не передан"} bad={!unsafe?.user} />
      <Row
        label="подпись в якоре"
        value={params.get("tgWebAppData") ? "есть" : "нет"}
        bad={!params.get("tgWebAppData")}
      />
      <Row
        label="что прислал Telegram"
        value={keys.length ? keys.join(", ") : "ничего"}
        bad={!keys.length}
      />
      <Row label="сохранённая подпись" value={saved ? `есть, ${saved.length} симв.` : "нет"} />
      <Row label="адрес" value={window.location.host} />

      <div className="divider" />
      <div className="hint" style={{ fontSize: 12 }}>
        {raw
          ? "Подпись пришла — значит дело в проверке на сервере."
          : "Подписи нет. Так бывает, если приложение открыто обычной ссылкой, " +
            "а не кнопкой «📡 Радар» или кнопкой меню рядом с полем ввода."}
      </div>
    </div>
  );
}
