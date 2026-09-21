import type { ReactNode } from "react";

export function Spinner() {
  return (
    <div className="center">
      <div className="spinner" />
    </div>
  );
}

export function Empty({ icon, title, hint }: { icon: string; title: string; hint?: string }) {
  return (
    <div className="center">
      <div style={{ fontSize: 34 }}>{icon}</div>
      <div className="strong" style={{ color: "var(--text)" }}>
        {title}
      </div>
      {hint && <div className="hint">{hint}</div>}
    </div>
  );
}

export function ErrorBanner({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="error-banner">
      {error}
      {onRetry && (
        <button className="btn ghost small" style={{ padding: "4px 0" }} onClick={onRetry}>
          Повторить
        </button>
      )}
    </div>
  );
}

export function Switch({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <button
      className={`switch ${on ? "on" : ""}`}
      onClick={onToggle}
      aria-pressed={on}
      aria-label={on ? "включено" : "выключено"}
    />
  );
}

export function Chips<T extends string | number>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: ReactNode }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="chips">
      {options.map((option) => (
        <button
          key={String(option.value)}
          className={`chip ${option.value === value ? "active" : ""}`}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span className="hint">{label}</span>
      {children}
    </label>
  );
}
