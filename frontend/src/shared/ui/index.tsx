import type { ReactNode } from 'react';
import type { Urgency } from '../types';

export function Icon({ name, size = 20, className = '' }: { name: string; size?: number; className?: string }) {
  const shapes: Record<string, ReactNode> = {
    bolt: <path d="m13 2-9 12h7l-1 8 10-13h-7l1-7Z" />,
    grid: <><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></>,
    box: <><path d="m12 3 9 5v8l-9 5-9-5V8l9-5Z"/><path d="m3 8 9 5 9-5M12 13v8m-4-15 9 5"/></>,
    chart: <><path d="M4 3v17h17M7 14l5-5 4 3 5-8"/></>,
    database: <><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 4 16 4 16 0V5M4 12v7c0 4 16 4 16 0v-7"/></>,
    orders: <><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6m-6 4h6m-6 4h3"/></>,
    arrow: <path d="M4 12h16m-6-6 6 6-6 6"/>,
    down: <path d="m6 9 6 6 6-6"/>,
    check: <path d="m5 12 4 4L19 6"/>,
    close: <path d="m6 6 12 12M6 18 18 6"/>,
    search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></>,
    play: <path d="m8 4 12 8-12 8V4Z"/>,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 7a7 7 0 0 1 12-1l2 2M4 16l2 2a7 7 0 0 0 12-1"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    warning: <><path d="m12 3 10 17H2L12 3Z"/><path d="M12 9v5m0 3h.01"/></>,
    upload: <><path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6"/></>,
    download: <><path d="M12 3v13m-5-5 5 5 5-5M4 16v5h16v-5"/></>,
    settings: <><path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="8" cy="18" r="2"/></>,
    shield: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/></>,
    info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/></>,
    warehouse: <><path d="m3 8 9-5 9 5v13H3V8Z"/><path d="M7 21V11h10v10M7 15h10m-10 3h10"/></>,
    spark: <><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z"/></>,
    link: <><path d="M14 3h7v7m0-7L11 13M10 5H4v15h15v-6"/></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">{shapes[name] || shapes.box}</svg>;
}

export const number = (value: number | string | undefined, digits = 1) => {
  const n = Number(value ?? 0);
  return Number.isFinite(n) ? new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits }).format(n) : '—';
};
export const unitLabel = (value: string) => ({ pcs: 'шт.', piece: 'шт.', pieces: 'шт.', m: 'м', kg: 'кг' }[value] || value);
export const date = (value?: string | null) => value ? new Date(value.length === 10 ? `${value}T12:00:00` : value).toLocaleDateString('ru-RU', { day: '2-digit', month: 'short', year: 'numeric' }) : '—';
export const urgencyLabels: Record<Urgency, string> = {
  critical: 'Критично', order_now: 'Заказать сейчас', reserve: 'Пополнить резерв', none: 'Запас достаточен', review: 'Нужна проверка',
};
export function Badge({ urgency }: { urgency: Urgency }) {
  return <span className={`badge ${urgency}`}><span className="badge-dot"/>{urgencyLabels[urgency] || urgency}</span>;
}
export function Empty({ icon = 'box', title, children }: { icon?: string; title: string; children?: ReactNode }) {
  return <div className="empty-state"><span className="empty-icon"><Icon name={icon} size={30}/></span><h3>{title}</h3><div>{children}</div></div>;
}
export function ErrorNotice({ message, onDismiss }: { message: string; onDismiss?: () => void }) {
  return <div className="notice error" role="alert"><Icon name="warning"/><span>{message}</span>{onDismiss && <button className="icon-button" aria-label="Закрыть ошибку" onClick={onDismiss}><Icon name="close"/></button>}</div>;
}
export function Toggle({ checked, onChange, label, hint, disabled }: { checked: boolean; onChange: (value: boolean) => void; label: string; hint?: string; disabled?: boolean }) {
  return <label className="toggle-label"><span><strong>{label}</strong>{hint && <small>{hint}</small>}</span><input type="checkbox" checked={checked} onChange={event => onChange(event.target.checked)} disabled={disabled}/><span className="toggle-track"/></label>;
}
