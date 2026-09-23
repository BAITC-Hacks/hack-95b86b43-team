import { useRef, useState } from 'react';
import type { Bootstrap, Issue, ValidationReport } from '../shared/types';
import { post } from '../shared/api/client';
import { date, Empty, ErrorNotice, Icon, number } from '../shared/ui';

const expected = [
  ['products.csv', 'Номенклатура'], ['categories.csv', 'Категории'], ['warehouses.csv', 'Склады'],
  ['suppliers.csv', 'Поставщики'], ['product_suppliers.csv', 'Условия поставок'], ['sales.csv', 'Продажи'],
  ['inventory.csv', 'Остатки'], ['stockouts.csv', 'Отсутствие товара'], ['inbound.csv', 'Товары в пути'],
];
const issueText = (value: Issue | string) => typeof value === 'string' ? value : `${value.file ? `${value.file}${value.row ? `:${value.row}` : ''} · ` : ''}${value.message}`;

export default function DataPage({ bootstrap, onImported }: { bootstrap: Bootstrap; onImported: () => Promise<void> }) {
  const { dataset } = bootstrap;
  const [files, setFiles] = useState<Record<string, string>>({});
  const [label, setLabel] = useState('Новая выгрузка');
  const [dates, setDates] = useState({ history_start: dataset.history_start, history_end: dataset.history_end, as_of_date: dataset.as_of_date });
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const [showWarnings, setShowWarnings] = useState(false);
  const [success, setSuccess] = useState(false);

  async function selectFiles(list: FileList | File[]) {
    setError(''); setReport(null); setSuccess(false);
    const chosen = [...list];
    const names = chosen.map(f => f.name);
    if (names.some((n, i) => names.indexOf(n) !== i)) { setError('Выбраны файлы с одинаковыми именами. Оставьте по одному CSV каждого типа.'); return; }
    const unexpected = names.filter(n => !expected.some(([name]) => name === n));
    if (unexpected.length) { setError(`Неизвестные файлы: ${unexpected.join(', ')}. Используйте девять CSV из контракта.`); return; }
    try {
      const loaded: Record<string, string> = {};
      for (const file of chosen) {
        if (file.size > 30 * 1024 * 1024) throw new Error(`${file.name}: файл больше 30 МБ. Подготовьте меньшую выгрузку для MVP.`);
        loaded[file.name] = await file.text();
      }
      setFiles(prev => ({ ...prev, ...loaded }));
    } catch (e) { setError((e as Error).message); }
  }

  async function upload() {
    setUploading(true); setError(''); setReport(null); setSuccess(false);
    try {
      const result = await post<{ valid: boolean; report: ValidationReport }>('/datasets', { label, ...dates, files });
      setReport(result.report);
      if (result.valid) { await onImported(); setSuccess(true); }
    } catch (e) { setError((e as Error).message); } finally { setUploading(false); }
  }

  const counts = dataset.row_counts || {};
  const count = (key: string) => counts[key] ?? counts[key.replace('.csv', '')] ?? 0;
  return <>
    <div className="dataset-banner"><span className="dataset-icon"><Icon name="database" size={30}/></span><div><div className="section-kicker">АКТИВНЫЙ НАБОР</div><h2>{dataset.label || 'Данные для расчёта'}</h2><p>{date(dataset.history_start)} — {date(dataset.history_end)} <span>·</span> Снимок на {date(dataset.as_of_date)}</p></div><a className="button secondary" href="/api/datasets/current/download"><Icon name="download" size={17}/>Скачать CSV</a></div>
    <div className="data-stats"><div><Icon name="orders"/><strong>{number(count('sales.csv'), 0)}</strong><span>строк продаж</span></div><div><Icon name="box"/><strong>{number(count('products.csv'), 0)}</strong><span>артикулов</span></div><div><Icon name="warehouse"/><strong>{number(count('warehouses.csv'), 0)}</strong><span>склада / складов</span></div><div><Icon name="shield"/><strong>{number((dataset.warnings || []).length, 0)}</strong><span>предупреждений</span></div></div>
    {!!(dataset.warnings || []).length && <section className="panel dataset-warnings"><button onClick={() => setShowWarnings(!showWarnings)} className="warnings-heading" aria-expanded={showWarnings}><span><Icon name="warning" size={19}/><strong>Ограничения качества данных</strong><small>{dataset.warnings.length}</small></span><Icon name="down" size={18}/></button>{showWarnings && <div className="issues-list">{dataset.warnings.map((warning, i) => <p key={i}>{issueText(warning)}</p>)}</div>}</section>}
    <div className="data-layout"><section className="panel import-panel"><div className="panel-heading"><div><span className="section-kicker">ПОДКЛЮЧИТЬ СВОИ ДАННЫЕ</span><h2>Загрузка выгрузки</h2></div><span className="period-badge">CSV · UTF-8</span></div><div className="import-body"><p className="section-description">Девять файлов проходят единый валидатор. Некорректные данные не заменят текущий набор.</p><label className="form-label">Название набора<input value={label} onChange={e => setLabel(e.target.value)} maxLength={120} placeholder="Например, выгрузка склада Алматы" disabled={uploading}/></label><div className="date-inputs"><label className="form-label">Начало истории<input type="date" value={dates.history_start} onChange={e => setDates({ ...dates, history_start: e.target.value })} disabled={uploading}/></label><label className="form-label">Конец истории<input type="date" value={dates.history_end} onChange={e => setDates({ ...dates, history_end: e.target.value })} disabled={uploading}/></label><label className="form-label">Дата расчёта<input type="date" value={dates.as_of_date} onChange={e => setDates({ ...dates, as_of_date: e.target.value })} disabled={uploading}/></label></div>
      <button className={`dropzone ${dragging ? 'dragging' : ''}`} onClick={() => fileInput.current?.click()} onDragOver={e => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={e => { e.preventDefault(); setDragging(false); void selectFiles(e.dataTransfer.files); }} disabled={uploading}><span><Icon name="upload" size={26}/></span><strong>Перетащите CSV сюда</strong><p>или нажмите, чтобы выбрать файлы</p><small>Можно добавить несколько файлов за один раз</small></button><input type="file" multiple accept=".csv,text/csv" ref={fileInput} className="visually-hidden" onChange={e => { if (e.target.files) void selectFiles(e.target.files); e.target.value = ''; }}/>
      <div className="file-checklist">{expected.map(([name, description]) => <div key={name} className={files[name] !== undefined ? 'loaded' : ''}><Icon name={files[name] !== undefined ? 'check' : 'orders'} size={16}/><span><strong>{name}</strong><small>{description}</small></span>{files[name] !== undefined && <button className="icon-button" aria-label={`Убрать ${name}`} disabled={uploading} onClick={() => setFiles(prev => { const next = { ...prev }; delete next[name]; return next; })}><Icon name="close" size={15}/></button>}</div>)}</div>
      {error && <ErrorNotice message={error}/>} {success && <div className="notice success"><Icon name="check"/><span>Проверка пройдена. Набор активен — можно запускать расчёт.</span></div>}
      {report && <div className={`import-report ${report.errors?.length ? 'has-errors' : ''}`}><h3>{report.errors?.length ? 'Нужно исправить данные' : 'Отчёт валидации'}</h3><p>Ошибок: {report.errors?.length || 0} · Предупреждений: {report.warnings?.length || 0}</p>{(report.errors || []).map((issue, i) => <div className="issue error-issue" key={`e${i}`}><strong>{issue.code}</strong><span>{issueText(issue)}</span></div>)}{(report.warnings || []).map((issue, i) => <div className="issue" key={`w${i}`}><strong>{issue.code}</strong><span>{issueText(issue)}</span></div>)}</div>}
      <div className="import-footer"><span>{Object.keys(files).length} из 9 файлов</span><button className="button primary" onClick={() => void upload()} disabled={uploading || Object.keys(files).length !== 9 || !label.trim() || !dates.as_of_date || !dates.history_start || !dates.history_end}>{uploading ? <span className="spinner small"/> : <Icon name="shield" size={18}/>}Проверить и подключить</button></div></div></section>
      <aside className="data-aside"><section className="panel guide-panel"><span className="guide-icon"><Icon name="shield" size={24}/></span><h3>Данные под контролем</h3><div className="guide-step"><span>01</span><div><strong>Без личных данных</strong><p>В продажах используйте только обезличенный ID клиента.</p></div></div><div className="guide-step"><span>02</span><div><strong>Один формат</strong><p>Даты YYYY-MM-DD, десятичная точка, разделитель — запятая. Остатки на начало даты расчёта.</p></div></div><div className="guide-step"><span>03</span><div><strong>Проверяем каждую строку</strong><p>Ошибки содержат имя файла, строку и поле. Плохие строки не исчезают молча.</p></div></div><a href="/api/datasets/current/download" className="text-button">Скачать образец <Icon name="arrow" size={17}/></a></section><div className="data-tip"><Icon name="info" size={20}/><p>Алгоритм работает с единым контрактом. Выгрузки «Электрокомплекта» можно подключить после приведения столбцов к этому формату.</p></div></aside></div>
  </>;
}
