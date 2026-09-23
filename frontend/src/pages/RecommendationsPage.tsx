import { useMemo, useState } from 'react';
import type { Dataset, Recommendation } from '../shared/types';
import { Badge, Empty, Icon, number, unitLabel } from '../shared/ui';
import { LineChart } from '../shared/ui/Charts';

const urgencyOrder = { critical: 0, review: 1, order_now: 2, reserve: 3, none: 4 };

export default function RecommendationsPage({ recommendations, overview, busy, onSelect, onViewAll, onCreateOrder, creatingOrder, dataset, previous }: {
  recommendations: Recommendation[]; overview: boolean; busy: boolean;
  onSelect: (r: Recommendation) => void; onViewAll: () => void;
  onCreateOrder: (supplier: string, rows: Recommendation[]) => void; creatingOrder: string | null;
  dataset: Dataset; previous: Record<string, number>;
}) {
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');
  const orderRows = recommendations.filter(r => Number(r.recommended_qty) > 0);
  const critical = recommendations.filter(r => r.urgency === 'critical');
  const suppliers = new Set(orderRows.map(r => r.supplier_id)).size;
  const uniqueSkus = new Set(recommendations.map(r => r.sku)).size;
  const missingDays = recommendations.reduce((n, r) => n + Number(r.stockout_days || 0), 0);
  const excluded = recommendations.reduce((n, r) => n + Number(r.excluded_events || 0), 0);
  const sorted = [...recommendations].sort((a, b) => urgencyOrder[a.urgency] - urgencyOrder[b.urgency] || a.sku.localeCompare(b.sku));
  const featured = recommendations.find(r => Number(r.excluded_events) > 0 && (r.chart || []).length) || recommendations.find(r => (r.chart || []).length);
  const visible = useMemo(() => sorted.filter(r => {
    const match = `${r.sku} ${r.name} ${r.supplier_name} ${r.warehouse_id}`.toLowerCase().includes(search.toLowerCase());
    return match && (filter === 'all' || filter === 'needed' && Number(r.recommended_qty) > 0 || r.urgency === filter);
  }), [sorted, search, filter]);
  const rows = overview ? visible.slice(0, 7) : visible;
  const groups = new Map<string, Recommendation[]>();
  for (const item of rows) groups.set(item.supplier_id, [...(groups.get(item.supplier_id) || []), item]);
  const available = recommendations.length > 0;

  return <>
    <div className="kpi-grid">
      <div className="kpi-card"><div className="kpi-top"><span>В анализе</span><span className="kpi-icon"><Icon name="box"/></span></div><div className="kpi-value">{available ? number(uniqueSkus, 0) : '—'}<span>артикулов</span></div><div className="kpi-detail">{available ? `${number(recommendations.length, 0)} позиций SKU × склад` : 'После первого расчёта'}</div></div>
      <div className="kpi-card"><div className="kpi-top"><span>К пополнению</span><span className="kpi-icon"><Icon name="orders"/></span></div><div className="kpi-value">{available ? number(orderRows.length, 0) : '—'}<span>позиций</span></div><div className="kpi-detail"><span className="tiny-dot green"/>Рекомендовано к заказу</div></div>
      <div className="kpi-card critical-card"><div className="kpi-top"><span>Риск дефицита</span><span className="kpi-icon"><Icon name="warning"/></span></div><div className="kpi-value">{available ? number(critical.length, 0) : '—'}<span>позиций</span></div><div className="kpi-detail">До ближайшей обычной поставки</div></div>
      <div className="kpi-card"><div className="kpi-top"><span>Поставщики</span><span className="kpi-icon"><Icon name="warehouse"/></span></div><div className="kpi-value">{available ? number(suppliers, 0) : '—'}<span>в расчёте</span></div><div className="kpi-detail">Заказы сгруппированы автоматически</div></div>
    </div>

    {overview && <div className="overview-grid">
      <section className="panel demand-panel"><div className="panel-heading"><div><span className="section-kicker">СПРОС БЕЗ ИСКАЖЕНИЙ</span><h2>За цифрами — реальная потребность</h2></div><span className="period-badge">История продаж</span></div>
        {featured ? <><div className="featured-product"><span className="product-mini-icon"><Icon name="bolt" size={18}/></span><button onClick={() => onSelect(featured)}><strong>{featured.name}</strong><small>{featured.sku} <span>·</span> {featured.warehouse_id}</small></button><span className="featured-unit">{unitLabel(featured.unit)}</span></div><LineChart data={(featured.chart || []).map(x => ({ ...x, observed: Number(x.observed), baseline: Number(x.baseline) }))} series={[{ key: 'baseline', label: 'Очищенный спрос', color: '#246857' }, { key: 'observed', label: 'Фактические продажи', color: '#acc753', dashed: true }]} ariaLabel={`История продаж и очищенный спрос ${featured.name}`} unit={unitLabel(featured.unit)}/><div className="chart-footnote"><Icon name="info" size={14}/>Месячные объёмы. Крупные события и отсутствие товара учитываются отдельно.</div></> : <div className="chart-placeholder"><div className="placeholder-grid"/><Icon name="chart" size={42}/><strong>{busy ? 'Находим закономерности спроса' : 'График появится после расчёта'}</strong><span>Реальная история из выбранного набора данных</span></div>}
      </section>
      <section className="insight-panel"><div className="insight-head"><span className="insight-icon"><Icon name="spark" size={22}/></span><span>ОБЪЯСНИМАЯ АНАЛИТИКА</span></div><h2>Меньше шума.<br/>Больше ясности.</h2><p>Расчёт замечает то, что легко упустить в таблице.</p><div className="insight-list"><div><span className="insight-item-icon"><Icon name="shield" size={18}/></span><div><strong>{available ? number(excluded, 0) : '—'} разовых событий</strong><small>Исключено из регулярного спроса</small></div></div><div><span className="insight-item-icon"><Icon name="clock" size={18}/></span><div><strong>{available ? number(missingDays, 0) : '—'} дней отсутствия</strong><small>Учтено по позициям SKU × склад</small></div></div><div><span className="insight-item-icon"><Icon name="chart" size={18}/></span><div><strong>Сезонность + тренд</strong><small>Каждая поправка доступна для проверки</small></div></div></div><button className="insight-link" onClick={() => featured ? onSelect(featured) : onViewAll()}>Посмотреть, как это работает <Icon name="arrow" size={18}/></button><span className="insight-decoration" aria-hidden="true"/></section>
    </div>}

    <section className="panel recommendations-panel">
      <div className="panel-heading"><div><span className="section-kicker">{overview ? 'ПРИОРИТЕТЫ НА СЕГОДНЯ' : 'ПЛАН ПО ПОСТАВЩИКАМ'}</span><h2>{overview ? 'Начните с важного' : 'Рекомендованные закупки'} <span className="count-label">{visible.length}</span></h2></div>{overview && <button className="text-button" onClick={onViewAll}>Все рекомендации <Icon name="arrow" size={17}/></button>}</div>
      <div className="table-toolbar"><div className="search-box"><Icon name="search" size={18}/><input aria-label="Поиск по артикулу, товару или поставщику" placeholder="Артикул, товар или поставщик…" value={search} onChange={e => setSearch(e.target.value)}/>{search && <button className="icon-button" onClick={() => setSearch('')} aria-label="Очистить поиск"><Icon name="close" size={15}/></button>}</div><div className="filter-tabs" aria-label="Фильтр рекомендаций">{[['all', 'Все'], ['critical', 'Критично'], ['needed', 'К заказу']].map(([key, label]) => <button key={key} className={filter === key ? 'active' : ''} onClick={() => setFilter(key)}>{label}</button>)}</div></div>
      {!available ? <Empty icon={busy ? 'refresh' : 'chart'} title={busy ? 'Готовим рекомендации' : 'Пока нет расчёта'}><p>{busy ? 'Анализируем историю и текущие запасы. Результат появится автоматически.' : 'Выберите склад и категорию, затем нажмите «Рассчитать закупки».'}</p></Empty> : !rows.length ? <Empty title="Ничего не найдено"><p>Измените поисковый запрос или фильтр срочности.</p></Empty> : <div className="table-scroll"><table className="recommendations-table"><thead><tr><th>Товар / артикул</th><th>Доступно</th><th>В пути</th><th>Заказать</th><th>Приоритет</th><th/></tr></thead><tbody>{[...groups].map(([supplierId, items]) => <SupplierRows key={supplierId} items={items} overview={overview} onSelect={onSelect} busy={busy || !!creatingOrder} creating={creatingOrder === supplierId} orderCount={recommendations.filter(r => r.supplier_id === supplierId && Number(r.recommended_qty) > 0).length} onCreate={() => onCreateOrder(supplierId, recommendations.filter(r => r.supplier_id === supplierId))} previous={previous}/>)}</tbody></table></div>}
      <div className="table-bottom"><span><Icon name="info" size={14}/>Количество рассчитывается в единицах каждого товара</span><span>{overview && visible.length > 7 ? `Показано 7 из ${visible.length}` : `Позиций: ${rows.length}`}</span></div>
    </section>
    {dataset.synthetic && <div className="demo-note"><Icon name="info" size={16}/><span>Демонстрационный набор: сценарии спроса, stockout и крупные клиентские события созданы синтетически. Рекомендации рассчитаны по этим данным.</span></div>}
  </>;
}

function SupplierRows({ items, overview, onSelect, onCreate, busy, creating, previous, orderCount }: {
  items: Recommendation[]; overview: boolean; onSelect: (r: Recommendation) => void;
  onCreate: () => void; busy: boolean; creating: boolean; previous: Record<string, number>; orderCount: number;
}) {
  const orderable = items.some(r => Number(r.recommended_qty) > 0);
  return <>{!overview && <tr className="supplier-row"><td colSpan={6}><div><span><Icon name="warehouse" size={17}/><strong>{items[0].supplier_name}</strong><small>{items.length} поз.</small></span><button className="button small secondary" onClick={onCreate} title="Включить все позиции к заказу этого поставщика из текущего расчёта" disabled={!orderable || busy}>{creating ? <span className="spinner small"/> : <Icon name="orders" size={15}/>}Собрать заказ · {orderCount}</button></div></td></tr>}{items.map(r => <tr key={r.id} className="product-row" onClick={() => onSelect(r)}><td><button className="product-cell" onClick={e => { e.stopPropagation(); onSelect(r); }}><span className={`table-product-icon ${r.urgency === 'critical' ? 'urgent' : ''}`}><Icon name="bolt" size={18}/></span><span><strong>{r.name}</strong><small><span className="sku">{r.sku}</span><span>·</span>{r.warehouse_id}{overview && <> · {r.supplier_name}</>}</small></span></button></td><td><strong className="tabular">{number(r.available_stock, 12)}</strong><small className="unit">{unitLabel(r.unit)}</small></td><td><span className={`tabular ${Number(r.inbound_qty) === 0 ? 'muted' : ''}`}>{number(r.inbound_qty, 12)}</span><small className="unit">{unitLabel(r.unit)}</small></td><td><span className={`order-quantity ${Number(r.recommended_qty) > 0 ? 'positive' : ''}`}>{number(r.recommended_qty_exact ?? r.recommended_qty, 12)}<small>{unitLabel(r.unit)}</small></span>{previous[r.id] !== undefined && previous[r.id] !== Number(r.recommended_qty) && <small className="quantity-delta">было {number(previous[r.id], 12)}</small>}</td><td><Badge urgency={r.urgency}/></td><td><button className="row-open" onClick={e => { e.stopPropagation(); onSelect(r); }} aria-label={`Обоснование ${r.sku}`}><Icon name="arrow" size={18}/></button></td></tr>)}</>;
}
