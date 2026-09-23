import { useEffect, useState } from 'react';
import { api, post } from '../shared/api/client';
import type { Order, OrderLine } from '../shared/types';
import { date, Empty, ErrorNotice, Icon, number, unitLabel } from '../shared/ui';

const normalizeOrder = (order: Order): Order => ({
  ...order, lines: order.lines.map(line => ({ ...line, quantity: line.quantity_exact ?? String(line.quantity) })),
});

export default function OrdersPage({ initialOrders, selectedOrderId, onSelectedOrder, onChange, onToast }: {
  initialOrders: Order[]; selectedOrderId: string | null; onSelectedOrder: (id: string | null) => void;
  onChange: () => Promise<void>; onToast: (text: string) => void;
}) {
  const [orders, setOrders] = useState(initialOrders);
  const [current, setCurrent] = useState<Order | null>(null);
  const [lines, setLines] = useState<OrderLine[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [filter, setFilter] = useState('all');
  useEffect(() => { setOrders(initialOrders); }, [initialOrders]);
  useEffect(() => {
    let active = true;
    if (!selectedOrderId) { setCurrent(null); return; }
    setBusy(true); setError('');
    void api<Order>(`/orders/${selectedOrderId}`).then(order => { if (active) { const normalized = normalizeOrder(order); setCurrent(normalized); setLines(normalized.lines); setConfirm(false); } }).catch(e => active && setError(e.message)).finally(() => active && setBusy(false));
    return () => { active = false; };
  }, [selectedOrderId]);
  const dirty = current ? JSON.stringify(lines) !== JSON.stringify(current.lines) : false;
  const invalid = lines.some(line => String(line.quantity).trim() === '' || !Number.isFinite(Number(line.quantity)) || Number(line.quantity) < 0 || Number(line.quantity) !== Number(line.recommended_qty) && (line.reason || '').trim().length < 3);
  const updateLine = (index: number, key: 'quantity' | 'reason', value: number | string) => setLines(prev => prev.map((line, i) => i === index ? { ...line, [key]: value } : line));

  async function save() {
    if (!current) return; setBusy(true); setError('');
    try {
      const updated = normalizeOrder(await api<Order>(`/orders/${current.id}`, { method: 'PATCH', body: JSON.stringify({ expected_version: current.version, lines: lines.map(({ recommendation_id, quantity, reason }) => ({ recommendation_id, quantity: String(quantity), reason })) }) }));
      setCurrent(updated); setLines(updated.lines); await onChange(); onToast('Изменения сохранены. Заказ готов к проверке.');
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function approve() {
    if (!current) return; setBusy(true); setError('');
    try {
      const updated = normalizeOrder(await post<Order>(`/orders/${current.id}/approve`, { expected_version: current.version }));
      setCurrent(updated); setLines(updated.lines); setConfirm(false); await onChange(); onToast('Заказ утверждён локально. CSV доступен для выгрузки.');
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  const visible = orders.filter(o => filter === 'all' || o.status === filter);
  return <>
    <div className="orders-summary"><div><span className="orders-summary-icon"><Icon name="orders" size={24}/></span><div><strong>{orders.length}</strong><span>Всего заказов</span></div></div><div><span className="orders-summary-icon draft"><Icon name="clock" size={24}/></span><div><strong>{orders.filter(o => o.status === 'draft').length}</strong><span>Ожидают проверки</span></div></div><div><span className="orders-summary-icon approved"><Icon name="check" size={24}/></span><div><strong>{orders.filter(o => o.status === 'approved').length}</strong><span>Утверждено</span></div></div></div>
    <div className="notice neutral"><Icon name="shield" size={19}/><span>Утверждение сохраняет решение менеджера. Заказы не отправляются поставщикам автоматически.</span></div>
    {error && <ErrorNotice message={error} onDismiss={() => setError('')}/>}
    <div className={`orders-layout ${current ? 'has-current' : ''}`}><section className="panel order-list-panel"><div className="panel-heading"><h2>Мои заказы</h2><span className="count-label">{visible.length}</span></div><div className="order-filter filter-tabs">{[['all', 'Все'], ['draft', 'Черновики'], ['approved', 'Утверждены']].map(([key, label]) => <button key={key} className={filter === key ? 'active' : ''} onClick={() => setFilter(key)}>{label}</button>)}</div>{visible.length ? <div className="order-list">{visible.map(order => <button key={order.id} className={`order-list-item ${selectedOrderId === order.id ? 'active' : ''}`} onClick={() => onSelectedOrder(order.id)}><div><span className={`order-status ${order.status}`}>{order.status === 'approved' ? 'Утверждён' : 'Черновик'}</span><small>{date(order.created_at)}</small></div><strong>{order.supplier_name}</strong><div><span>{order.lines?.length || 0} позиций · №{order.id.slice(-7).toUpperCase()}</span><Icon name="arrow" size={17}/></div></button>)}</div> : <Empty icon="orders" title="Здесь появятся ваши заказы"><p>В разделе «Рекомендации» нажмите «Собрать заказ» у нужного поставщика.</p></Empty>}</section>
      {current && <section className="panel order-editor"><div className="panel-heading"><div><span className="section-kicker">ЗАКАЗ №{current.id.slice(-7).toUpperCase()}</span><h2>{current.supplier_name}</h2></div><button className="icon-button" onClick={() => onSelectedOrder(null)} aria-label="Закрыть заказ"><Icon name="close"/></button></div><div className="order-editor-meta"><span className={`order-status ${current.status}`}>{current.status === 'approved' ? 'Утверждён' : 'Черновик'}</span><span>Версия {current.version}</span><span>{date(current.created_at)}</span></div><div className="order-lines">{lines.map((line, i) => <div className="order-line" key={line.recommendation_id}><div className="order-line-title"><strong>{line.name}</strong><small>{line.sku} · {line.warehouse_id}</small></div><div className="order-quantity-fields"><div><label>Рекомендация</label><span>{number(line.recommended_qty_exact ?? line.recommended_qty, 12)} {unitLabel(line.unit)}</span></div><label>К заказу<div className="quantity-input"><input aria-label={`Количество для ${line.sku}`} type="number" min="0" step="any" value={line.quantity} onChange={e => updateLine(i, 'quantity', e.target.value)} disabled={busy || current.status === 'approved'}/><span>{unitLabel(line.unit)}</span></div></label></div>{(Number(line.quantity) !== Number(line.recommended_qty) || line.reason) && <label className="form-label edit-reason">Причина корректировки<input value={line.reason || ''} placeholder="Например, согласованная закупка под проект" aria-label={`Причина корректировки ${line.sku}`} onChange={e => updateLine(i, 'reason', e.target.value)} disabled={busy || current.status === 'approved'}/>{Number(line.quantity) !== Number(line.recommended_qty) && (line.reason || '').trim().length < 3 && <small className="field-error">Укажите причину изменения: минимум 3 символа</small>}</label>}</div>)}</div>
      {current.status === 'approved' ? <div className="order-actions approved-actions"><span><Icon name="check" size={18}/>Решение зафиксировано</span><a className="button primary" href={`/api/orders/${current.id}/export`}><Icon name="download" size={17}/>Скачать CSV</a></div> : <div className="order-actions"><button className="button secondary" disabled={!dirty || busy || invalid} onClick={() => void save()}>{busy ? <span className="spinner small"/> : <Icon name="check" size={17}/>}Сохранить правки</button><button className="button primary" disabled={dirty || busy || invalid || !lines.some(l => Number(l.quantity) > 0)} onClick={() => setConfirm(true)}><Icon name="shield" size={17}/>Утвердить заказ</button>{dirty && <small>Перед утверждением сохраните изменения.</small>}</div>}
      </section>}
      {!current && orders.length > 0 && <section className="panel order-prompt"><Empty icon="shield" title="Проверьте перед утверждением"><p>Выберите заказ, скорректируйте количество и сохраните решение. Утверждённый заказ можно экспортировать в CSV.</p></Empty></section>}
    </div>
    {confirm && current && <div className="confirm-overlay" onMouseDown={e => { if (e.target === e.currentTarget && !busy) setConfirm(false); }}><section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-title"><span className="confirm-icon"><Icon name="shield" size={30}/></span><h2 id="confirm-title">Утвердить заказ?</h2><p>Поставщик: <strong>{current.supplier_name}</strong><br/>{lines.filter(l => Number(l.quantity) > 0).length} позиций с положительным количеством. После утверждения этот заказ нельзя редактировать.</p><div className="notice neutral"><Icon name="info" size={17}/><span>Заказ будет сохранён локально. Отправки поставщику не произойдёт.</span></div><div className="confirm-actions"><button className="button secondary" disabled={busy} onClick={() => setConfirm(false)}>Вернуться к проверке</button><button className="button primary" disabled={busy} onClick={() => void approve()}>{busy ? <span className="spinner small"/> : <Icon name="check" size={17}/>}Подтвердить</button></div></section></div>}
  </>;
}
