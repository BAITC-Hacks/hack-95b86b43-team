import { useId, useState } from 'react';
import { number } from './index';

interface Series { key: string; label: string; color: string; dashed?: boolean }
export function LineChart({ data, series, height = 210, unit = '', ariaLabel }: {
  data: { date: string; [key: string]: string | number }[]; series: Series[]; height?: number; unit?: string; ariaLabel: string;
}) {
  const id = useId().replace(/:/g, '');
  const [hovered, setHovered] = useState<number | null>(null);
  if (!data.length) return <div className="chart-empty">Для графика пока нет наблюдений</div>;
  const width = 720; const pad = { l: 52, r: 16, t: 22, b: 30 };
  const values = data.flatMap(row => series.map(s => Number(row[s.key]) || 0));
  const min = Math.min(0, ...values); const max = Math.max(1, ...values) * 1.12;
  const x = (i: number) => pad.l + i / Math.max(1, data.length - 1) * (width - pad.l - pad.r);
  const y = (v: number) => pad.t + (max - v) / (max - min) * (height - pad.t - pad.b);
  const path = (key: string) => data.map((d, i) => `${i ? 'L' : 'M'}${x(i)},${y(Number(d[key]) || 0)}`).join(' ');
  const tickIndices = [...new Set([0, Math.round((data.length - 1) * .25), Math.round((data.length - 1) * .5), Math.round((data.length - 1) * .75), data.length - 1])];
  const point = hovered === null ? null : data[hovered];
  return <div className="chart-wrap">
    <svg className="line-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel}
      onMouseLeave={() => setHovered(null)} onMouseMove={event => {
        const rect = event.currentTarget.getBoundingClientRect();
        const px = (event.clientX - rect.left) / rect.width * width;
        setHovered(Math.max(0, Math.min(data.length - 1, Math.round((px - pad.l) / (width - pad.l - pad.r) * (data.length - 1)))));
      }}>
      <defs><linearGradient id={id} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={series[0].color} stopOpacity=".16"/><stop offset="100%" stopColor={series[0].color} stopOpacity="0"/></linearGradient></defs>
      {[0, 1, 2, 3].map(i => { const value = min + (max - min) * i / 3; return <g key={i}><line x1={pad.l} x2={width - pad.r} y1={y(value)} y2={y(value)} stroke="#e7ebe5" strokeDasharray="3 5"/><text x={pad.l - 10} y={y(value) + 4} textAnchor="end" className="chart-axis">{number(value, 0)}</text></g>; })}
      <path d={`${path(series[0].key)} L${x(data.length - 1)},${y(0)} L${x(0)},${y(0)} Z`} fill={`url(#${id})`}/>
      {min < 0 && <line x1={pad.l} x2={width - pad.r} y1={y(0)} y2={y(0)} stroke="#c26c55" strokeDasharray="4 4"/>}
      {series.map(s => <path key={s.key} d={path(s.key)} fill="none" stroke={s.color} strokeWidth="2.5" strokeDasharray={s.dashed ? '6 5' : undefined} strokeLinejoin="round" strokeLinecap="round"/>)}
      {tickIndices.map(i => <text key={i} x={x(i)} y={height - 7} textAnchor={i === 0 ? 'start' : i === data.length - 1 ? 'end' : 'middle'} className="chart-axis">{new Date(`${data[i].date.slice(0, 10)}T12:00:00`).toLocaleDateString('ru-RU', { day: data.length > 35 ? undefined : 'numeric', month: 'short' })}</text>)}
      {hovered !== null && <g><line x1={x(hovered)} x2={x(hovered)} y1={pad.t} y2={height - pad.b} stroke="#96aaa2" strokeDasharray="3 4"/>{series.map(s => <circle key={s.key} cx={x(hovered)} cy={y(Number(data[hovered][s.key]) || 0)} r="4" fill={s.color} stroke="white" strokeWidth="2"/>)}</g>}
    </svg>
    {point && <div className="chart-tooltip"><strong>{new Date(`${String(point.date).slice(0, 10)}T12:00:00`).toLocaleDateString('ru-RU')}</strong>{series.map(s => <span key={s.key}><i style={{ background: s.color }}/>{s.label}: <b>{number(point[s.key])} {unit}</b></span>)}</div>}
    <div className="chart-legend">{series.map(s => <span key={s.key}><i style={{ background: s.color }}/>{s.label}</span>)}{unit && <small>Единица: {unit}</small>}</div>
  </div>;
}

export function SeasonChart({ values }: { values: number[] }) {
  const months = ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек'];
  const max = Math.max(1, ...values.map(Number));
  return <div className="season-chart" role="img" aria-label="Сезонные коэффициенты по месяцам">{values.map((v, i) => <div key={i} className="season-column" title={`${months[i]}: ${number(v, 2)}`}><span>{number(v, 2)}</span><div style={{ height: `${Math.max(4, Number(v) / max * 70)}px` }} className={v > 1 ? 'high' : ''}/><small>{months[i]}</small></div>)}</div>;
}
