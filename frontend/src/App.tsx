type Recommendation = {
  code: string;
  article: string;
  supplier: string;
  demand: number;
  incoming: number;
  order: number;
  risk: 'Низкий' | 'Средний' | 'Высокий';
  riskClass: 'low' | 'medium' | 'high';
  status: 'Готово' | 'Проверка' | 'Дефицит';
  statusClass: 'ready' | 'review' | 'shortage';
};

const recommendations: Recommendation[] = [
  { code: 'S-1048', article: 'Кабель 3x2.5', supplier: 'Systeme', demand: 420, incoming: 180, order: 260, risk: 'Высокий', riskClass: 'high', status: 'Дефицит', statusClass: 'shortage' },
  { code: 'S-2041', article: 'Коробка распаечная', supplier: 'Systeme', demand: 310, incoming: 140, order: 210, risk: 'Средний', riskClass: 'medium', status: 'Проверка', statusClass: 'review' },
  { code: 'S-3079', article: 'DIN-рейка 12 мод.', supplier: 'Systeme', demand: 680, incoming: 420, order: 280, risk: 'Низкий', riskClass: 'low', status: 'Готово', statusClass: 'ready' },
  { code: 'S-1882', article: 'Автомат 16A', supplier: 'Systeme', demand: 260, incoming: 160, order: 120, risk: 'Средний', riskClass: 'medium', status: 'Проверка', statusClass: 'review' },
];

const chartValues = [42, 48, 46, 62, 58, 74, 80, 78, 92, 98, 88, 106];

const kpis = [
  { label: 'Покрытие', value: '96%', note: '+4.2% за 7 дней' },
  { label: 'Критические позиции', value: '12', note: 'Из 148 SKU' },
  { label: 'Прогноз спроса', value: '18.4k', note: 'На 14 дней' },
  { label: 'Подтверждено заявок', value: '84%', note: '6 заявок в работе' },
];

const priorities = [
  'Быстрая проверка по MOQ',
  'Коррекция остатка по 3 складам',
  'Подтверждение поставки 27.09',
  'Экспорт рекомендаций в ERP',
];

const appStyles = `
  :root {
    font-family: 'Inter', sans-serif;
    color: #0f172a;
    background: #edf3ff;
    line-height: 1.5;
    font-weight: 400;
    font-synthesis: none;
    text-rendering: optimizeLegibility;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    --bg: #edf3ff;
    --panel: #ffffff;
    --panel-alt: #f5f8ff;
    --line: #dfe7f7;
    --primary: #2d6df6;
    --primary-strong: #1e4fc7;
    --primary-soft: #eaf1ff;
    --text: #13213d;
    --muted: #66789d;
    --success: #1bb882;
    --warning: #ffb020;
    --danger: #f15b6c;
    --shadow: 0 12px 28px rgba(42, 78, 148, 0.08);
  }

  * { box-sizing: border-box; }

  html, body, #root {
    margin: 0;
    min-height: 100%;
    background: var(--bg);
  }

  body {
    min-height: 100vh;
    color: var(--text);
  }

  button { font: inherit; }

  .app-shell { display: flex; min-height: 100vh; background: linear-gradient(135deg, #eef4ff 0%, #edf4fb 100%); }
  .sidebar {
    width: 260px;
    background: rgba(12, 24, 48, 0.96);
    color: #edf4ff;
    padding: 28px 18px;
    display: flex;
    flex-direction: column;
    gap: 26px;
  }

  .brand-wrap { display: flex; align-items: center; gap: 12px; padding: 8px 10px 18px; border-bottom: 1px solid rgba(186, 203, 255, 0.15); }
  .brand-mark {
    display: grid; place-items: center; width: 42px; height: 42px; border-radius: 12px; background: linear-gradient(135deg, #6aa6ff, #4267f5); font-weight: 800;
  }
  .brand-label { font-size: 1.1rem; font-weight: 700; }
  .brand-subtitle { color: rgba(237, 244, 255, 0.7); font-size: 0.74rem; }
  .nav { display: flex; flex-direction: column; gap: 8px; }
  .nav-item {
    border: 0; background: transparent; color: rgba(237, 244, 255, 0.8); text-align: left; padding: 12px 14px; border-radius: 10px; font-weight: 600; cursor: pointer; transition: all 0.2s ease;
  }
  .nav-item.active, .nav-item:hover { background: rgba(255, 255, 255, 0.08); color: #fff; }
  .mini-card {
    margin-top: auto; background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(196, 213, 255, 0.12); border-radius: 16px; padding: 18px 16px;
  }
  .mini-card__title { color: rgba(237, 244, 255, 0.7); font-size: 0.76rem; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.08em; }
  .mini-card__value { font-size: 1.4rem; font-weight: 700; margin-bottom: 4px; }
  .mini-card__meta { color: rgba(237, 244, 255, 0.7); font-size: 0.78rem; }
  .main-panel { flex: 1; padding: 28px 32px 40px; }
  .topbar { display: flex; justify-content: space-between; align-items: center; gap: 20px; margin-bottom: 28px; }
  .eyebrow { margin: 0 0 8px; color: var(--muted); font-size: 0.76rem; letter-spacing: 0.08em; font-weight: 700; text-transform: uppercase; }
  h1, h2 { margin: 0; color: var(--text); }
  h1 { font-size: clamp(1.8rem, 2vw + 1rem, 2.8rem); }
  h2 { font-size: 1.2rem; }
  .toolbar { display: flex; align-items: center; gap: 14px; }
  .search-box { min-width: 220px; padding: 12px 14px; border-radius: 12px; background: rgba(255, 255, 255, 0.75); border: 1px solid var(--line); color: var(--muted); font-size: 0.92rem; }
  .primary-btn, .secondary-btn { border: 0; border-radius: 12px; padding: 11px 16px; cursor: pointer; font-weight: 700; }
  .primary-btn { background: linear-gradient(135deg, var(--primary), var(--primary-strong)); color: #fff; box-shadow: var(--shadow); }
  .secondary-btn { background: var(--primary-soft); color: var(--primary-strong); }
  .kpi-grid { display: grid; grid-template-columns: repeat(4, minmax(180px, 1fr)); gap: 18px; margin-bottom: 26px; }
  .kpi-card, .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 18px; box-shadow: var(--shadow); }
  .kpi-card { padding: 18px 18px 16px; }
  .kpi-label { color: var(--muted); font-size: 0.8rem; margin-bottom: 14px; }
  .kpi-value { font-size: clamp(1.7rem, 1.5vw + 1rem, 2.5rem); font-weight: 800; letter-spacing: -0.04em; margin-bottom: 10px; }
  .kpi-note { color: var(--muted); font-size: 0.8rem; }
  .content-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 20px; margin-bottom: 24px; }
  .panel { padding: 20px 22px; }
  .panel-large { min-height: 330px; }
  .panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; gap: 16px; }
  .compact { margin-bottom: 12px; }
  .badge { display: inline-flex; align-items: center; padding: 6px 10px; border-radius: 999px; font-size: 0.76rem; font-weight: 700; }
  .badge.success { background: rgba(27, 184, 130, 0.12); color: var(--success); }
  .chart { width: 100%; height: 240px; border-radius: 14px; background: linear-gradient(180deg, rgba(102, 153, 255, 0.04), rgba(102, 153, 255, 0)); overflow: hidden; }
  .chart svg { width: 100%; height: 100%; display: block; }
  .task-list { list-style: none; margin: 18px 0 0; padding: 0; display: flex; flex-direction: column; gap: 12px; }
  .task-list li { position: relative; padding: 12px 12px 12px 42px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel-alt); color: var(--text); font-weight: 600; }
  .task-list li::before { content: ""; position: absolute; left: 16px; top: 16px; width: 12px; height: 12px; border-radius: 50%; background: linear-gradient(135deg, var(--primary), #7ca5ff); }
  .table-panel { overflow: hidden; }
  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; min-width: 720px; }
  th, td { padding: 14px 12px; text-align: left; border-bottom: 1px solid var(--line); font-size: 0.95rem; }
  th { color: var(--muted); font-size: 0.76rem; text-transform: uppercase; letter-spacing: 0.06em; background: rgba(245, 248, 255, 0.9); }
  .risk, .status { display: inline-flex; align-items: center; justify-content: center; min-width: 86px; padding: 8px 10px; border-radius: 999px; font-size: 0.78rem; font-weight: 700; }
  .risk-high, .status-shortage { background: rgba(241, 91, 108, 0.12); color: var(--danger); }
  .risk-medium, .status-review { background: rgba(255, 176, 32, 0.12); color: #ac6c00; }
  .risk-low, .status-ready { background: rgba(27, 184, 130, 0.12); color: var(--success); }

  @media (max-width: 960px) {
    .app-shell { flex-direction: column; }
    .sidebar { width: 100%; }
    .content-grid { grid-template-columns: 1fr; }
    .kpi-grid { grid-template-columns: repeat(2, minmax(160px, 1fr)); }
  }

  @media (max-width: 640px) {
    .main-panel { padding: 18px 16px 24px; }
    .topbar { flex-direction: column; align-items: flex-start; }
    .toolbar { width: 100%; justify-content: space-between; }
    .search-box { flex: 1; min-width: 0; }
    .kpi-grid { grid-template-columns: 1fr; }
  }
`;

function App() {
  return (
    <>
      <style>{appStyles}</style>
      <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-wrap">
          <div className="brand-mark">S</div>
          <div>
            <div className="brand-label">Systeme</div>
            <div className="brand-subtitle">Planning Hub</div>
          </div>
        </div>

        <nav className="nav">
          <button className="nav-item active">Обзор</button>
          <button className="nav-item">Спрос</button>
          <button className="nav-item">Рекомендации</button>
          <button className="nav-item">Заказы</button>
          <button className="nav-item">Импорт</button>
        </nav>

        <div className="mini-card">
          <div className="mini-card__title">Сценарий</div>
          <div className="mini-card__value">baseline-v3</div>
          <div className="mini-card__meta">Последний пересчёт: 08:45</div>
        </div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div>
            <p className="eyebrow">Планирование поставок</p>
            <h1>Сводка по запасам и рекомендациям</h1>
          </div>

          <div className="toolbar">
            <div className="search-box">Поиск товара / кода</div>
            <button className="primary-btn">Экспорт</button>
          </div>
        </header>

        <section className="kpi-grid">
          {kpis.map((card) => (
            <div className="kpi-card" key={card.label}>
              <div className="kpi-label">{card.label}</div>
              <div className="kpi-value">{card.value}</div>
              <div className="kpi-note">{card.note}</div>
            </div>
          ))}
        </section>

        <section className="content-grid">
          <div className="panel panel-large">
            <div className="panel-header">
              <div>
                <p className="eyebrow">Прогноз спроса</p>
                <h2>Суточный спрос по горизонту</h2>
              </div>
              <span className="badge success">+12.4%</span>
            </div>

            <div className="chart" aria-label="График спроса">
              <svg viewBox="0 0 620 220" role="img" aria-label="Forecast chart">
                <defs>
                  <linearGradient id="areaGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#6aa6ff" stopOpacity="0.45" />
                    <stop offset="100%" stopColor="#6aa6ff" stopOpacity="0.02" />
                  </linearGradient>
                </defs>
                {[0, 1, 2, 3].map((line) => (
                  <line key={line} x1="0" x2="620" y1={30 + line * 50} y2={30 + line * 50} stroke="#dfe7f5" strokeDasharray="5 5" />
                ))}
                <path
                  d="M0 150 C70 120, 110 90, 160 94 S250 80, 310 76 S420 122, 500 110 S570 50, 620 42 L620 220 L0 220 Z"
                  fill="url(#areaGradient)"
                />
                <path
                  d="M0 150 C70 120, 110 90, 160 94 S250 80, 310 76 S420 122, 500 110 S570 50, 620 42"
                  fill="none"
                  stroke="#437dff"
                  strokeWidth="4"
                  strokeLinecap="round"
                />
                {chartValues.map((value, index) => {
                  const x = 18 + index * 54;
                  const y = 200 - value;
                  return <circle key={index} cx={x} cy={y} r="4" fill="#437dff" />;
                })}
              </svg>
            </div>
          </div>

          <div className="panel">
            <div className="panel-header compact">
              <div>
                <p className="eyebrow">Приоритеты</p>
                <h2>Что важно сейчас</h2>
              </div>
            </div>

            <ul className="task-list">
              {priorities.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </section>

        <section className="table-panel panel">
          <div className="panel-header compact">
            <div>
              <p className="eyebrow">Рекомендации</p>
              <h2>Товары к закупке</h2>
            </div>
            <button className="secondary-btn">Показать все</button>
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Код</th>
                  <th>Артикул</th>
                  <th>Потребность</th>
                  <th>В пути</th>
                  <th>Заказ</th>
                  <th>Риск</th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>
                {recommendations.map((row) => (
                  <tr key={row.code}>
                    <td>{row.code}</td>
                    <td>{row.article}</td>
                    <td>{row.demand}</td>
                    <td>{row.incoming}</td>
                    <td>{row.order}</td>
                    <td>
                      <span className={`risk risk-${row.riskClass}`}>{row.risk}</span>
                    </td>
                    <td>
                      <span className={`status status-${row.statusClass}`}>{row.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </main>
      </div>
    </>
  );
}

export default App;
