import { useCallback, useEffect, useRef, useState } from 'react';
import { api, post } from '../shared/api/client';
import type { Bootstrap, CalculationSettings, Recommendation, Run, Order } from '../shared/types';
import { Icon, number, date, ErrorNotice } from '../shared/ui';
import RecommendationsPage from '../pages/RecommendationsPage';
import ProductPage from '../pages/ProductPage';
import DataPage from '../pages/DataPage';
import OrdersPage from '../pages/OrdersPage';
import CalculationPage from '../pages/CalculationPage';

type Page = 'overview' | 'recommendations' | 'data' | 'orders';
const defaultSettings: CalculationSettings = {
  warehouse_id: null, category_id: null, review_days: 7, safety_days: 5,
  use_stockout: true, use_outliers: true, use_seasonality: true, use_trend: true,
};

export default function App() {
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [page, setPage] = useState<Page>('overview');
  const [settings, setSettings] = useState(defaultSettings);
  const [run, setRun] = useState<Run | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [previous, setPrevious] = useState<Record<string, number>>({});
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [openOrder, setOpenOrder] = useState<string | null>(null);
  const [creatingOrder, setCreatingOrder] = useState<string | null>(null);
  const booted = useRef(false);
  const recommendations = run?.result?.recommendations || [];
  const selected = recommendations.find(r => r.id === selectedId) || null;

  const refresh = useCallback(async () => {
    const result = await api<Bootstrap>('/bootstrap'); setBootstrap(result); return result;
  }, []);

  const startCalculation = useCallback(async (nextSettings: CalculationSettings, compare = false) => {
    setError(''); setBusy(true); setSettings(nextSettings);
    if (compare) setPrevious(Object.fromEntries(recommendations.map(r => [r.id, Number(r.recommended_qty)])));
    else setPrevious({});
    try {
      const response = await post<{ run_id: string; status: Run['status'] }>('/calculations', nextSettings);
      setRunId(response.run_id);
      setRun(old => ({ ...old, run_id: response.run_id, status: response.status, progress: 0, message: 'Готовим данные и рассчитываем потребность…' }));
    } catch (e) { setError((e as Error).message); setPrevious({}); setBusy(false); }
  }, [recommendations]);

  useEffect(() => {
    if (booted.current) return; booted.current = true;
    void refresh().then(async data => {
      const latest = data.runs?.find(r => r.dataset_id === data.dataset.id && (r.status === 'completed' || r.status === 'running' || r.status === 'queued'));
      if (latest) { setRunId(latest.run_id); setBusy(latest.status !== 'completed'); }
      else await startCalculation(defaultSettings);
    }).catch(e => setError(e.message));
  }, [refresh, startCalculation]);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false; let timeout: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const result = await api<Run>(`/calculations/${runId}`);
        if (cancelled) return;
        if (result.status === 'completed') { setRun(result); setBusy(false); if (result.options) setSettings(result.options); void refresh(); }
        else if (result.status === 'failed') { setRun(result); setBusy(false); setError(result.error || result.message || 'Расчёт не завершён'); }
        else { setRun(old => ({ ...result, result: old?.result })); setBusy(true); timeout = setTimeout(poll, 1100); }
      } catch (e) { if (!cancelled) { setError((e as Error).message); setBusy(false); } }
    }
    void poll(); return () => { cancelled = true; clearTimeout(timeout); };
  }, [runId, refresh]);

  useEffect(() => { if (!toast) return; const timer = setTimeout(() => setToast(''), 5500); return () => clearTimeout(timer); }, [toast]);

  async function createOrder(supplierId: string, rows: Recommendation[]) {
    if (!run || busy) return; setCreatingOrder(supplierId); setError('');
    try {
      const order = await post<Order>('/orders', { run_id: run.run_id, supplier_id: supplierId, lines: rows.filter(r => Number(r.recommended_qty) > 0).map(r => ({ recommendation_id: r.id, quantity: r.recommended_qty_exact ?? r.recommended_qty, reason: '' })) });
      setOpenOrder(order.id); setPage('orders'); setSelectedId(null); await refresh(); setToast('Черновик заказа создан. Проверьте количество перед утверждением.');
    } catch (e) { setError((e as Error).message); } finally { setCreatingOrder(null); }
  }

  const navigate = (next: Page) => { setPage(next); setSelectedId(null); };
  const pageNames: Record<Page, string> = { overview: 'Обзор закупок', recommendations: 'Рекомендации', data: 'Источники данных', orders: 'Заказы поставщикам' };
  const pendingOrders = bootstrap?.orders?.filter(o => o.status === 'draft').length || 0;
  return <div className="app-shell">
    <aside className="sidebar">
      <button className="brand" onClick={() => navigate('overview')} aria-label="На главную"><span className="brand-mark"><Icon name="bolt" size={26}/></span><span>контур<span className="brand-subtitle">закупок</span></span></button>
      <div className="workspace-label">РАБОЧЕЕ ПРОСТРАНСТВО</div>
      <nav className="main-nav" aria-label="Основная навигация">
        {([['overview', 'grid', 'Обзор'], ['recommendations', 'chart', 'Рекомендации'], ['orders', 'orders', 'Заказы'], ['data', 'database', 'Данные']] as [Page, string, string][]).map(([key, icon, label]) => <button key={key} aria-label={label} className={`nav-item ${page === key ? 'active' : ''}`} onClick={() => navigate(key)}><Icon name={icon}/><span>{label}</span>{key === 'orders' && pendingOrders > 0 && <span className="nav-count">{pendingOrders}</span>}{key === 'recommendations' && recommendations.length > 0 && <span className="nav-count">{recommendations.length}</span>}</button>)}
      </nav>
      <div className="sidebar-note"><span className="note-icon"><Icon name="shield"/></span><strong>Решение остаётся за вами</strong><p>Система рекомендует. Вы проверяете и утверждаете каждый заказ.</p><div className="note-rule"/><small>Без автоматической отправки</small></div>
      <div className="sidebar-bottom"><div className="partner-monogram">ЭК</div><div><strong>Электрокомплект</strong><span>HACKALEM AI · 2026</span></div></div>
    </aside>

    <div className="main-shell">
      <header className="topbar"><div className="breadcrumb">Рабочее пространство <span>/</span> <strong>{pageNames[page]}</strong></div><div className="topbar-right"><span className={`connection ${bootstrap ? '' : 'pending'}`}><i/>{bootstrap ? 'Система готова' : 'Подключение'}</span><span className="topbar-divider"/><span className="avatar">МЗ</span><span className="user-name">Менеджер закупа</span></div></header>
      <main className="main-content">
        <div className="page-heading"><div><div className="eyebrow">ПЛАНИРОВАНИЕ С УВЕРЕННОСТЬЮ</div><h1>{pageNames[page]}</h1><p>{page === 'data' ? 'Единый контракт для демонстрационных данных и выгрузок 1С.' : page === 'orders' ? 'От рекомендации до проверенного заказа — под вашим контролем.' : 'Нужный товар. В нужном количестве. В нужный момент.'}</p></div><div className="heading-meta">{bootstrap?.dataset?.synthetic && <span className="demo-badge"><Icon name="spark" size={14}/>Демо · синтетические данные</span>}<span className="date-label"><Icon name="clock" size={15}/>На {date(bootstrap?.dataset?.as_of_date)}</span></div></div>
        {error && <ErrorNotice message={error} onDismiss={() => setError('')}/>}
        {!bootstrap && !error && <div className="bootstrap-loading"><span className="spinner"/><h3>Подключаем рабочее пространство</h3><p>Загружаем источники и последние расчёты</p></div>}
        {!bootstrap && error && <button className="button primary" onClick={() => { setError(''); void refresh().then(() => startCalculation(defaultSettings)).catch(e => setError(e.message)); }}><Icon name="refresh"/>Повторить подключение</button>}
        {bootstrap && (page === 'overview' || page === 'recommendations') && <>
          <CalculationPage settings={settings} onChange={setSettings} bootstrap={bootstrap} busy={busy} run={run} onRun={() => void startCalculation(settings)} settingsOpen={settingsOpen} onSettingsToggle={() => setSettingsOpen(!settingsOpen)} onScenario={() => void startCalculation(settings, true)}/>
          <RecommendationsPage recommendations={recommendations} overview={page === 'overview'} busy={busy} onSelect={r => setSelectedId(r.id)} onViewAll={() => navigate('recommendations')} onCreateOrder={createOrder} creatingOrder={creatingOrder} dataset={bootstrap.dataset} previous={previous}/>
        </>}
        {bootstrap && page === 'data' && <DataPage bootstrap={bootstrap} onImported={async () => { await refresh(); setRun(null); setRunId(null); setBusy(false); setSelectedId(null); setPrevious({}); setSettings(defaultSettings); setToast('Данные проверены и подключены. Запустите новый расчёт.'); }}/>}
        {bootstrap && page === 'orders' && <OrdersPage initialOrders={bootstrap.orders || []} selectedOrderId={openOrder} onSelectedOrder={setOpenOrder} onChange={async () => { await refresh(); }} onToast={setToast}/>}
        <footer className="page-footer"><span><Icon name="shield" size={14}/>Каждая рекомендация объяснима и проверяема</span><span>Контур закупок <i/> HACKALEM AI</span></footer>
      </main>
    </div>
    {selected && <ProductPage item={selected} onClose={() => setSelectedId(null)} previousQty={previous[selected.id]} settings={settings} onScenario={next => void startCalculation(next, true)} busy={busy || !!creatingOrder} calculating={busy} onCreateOrder={() => void createOrder(selected.supplier_id, recommendations.filter(r => r.supplier_id === selected.supplier_id))}/>}
    {toast && <div className="toast" role="status"><span><Icon name="check"/></span>{toast}<button className="icon-button" onClick={() => setToast('')} aria-label="Закрыть уведомление"><Icon name="close" size={16}/></button></div>}
  </div>;
}
