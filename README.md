# HACKALEM AI — заказы поставщикам

Проект команды «Луксмаксеры» для ТОО «Электрокомплект»: расчёт рекомендаций по пополнению склада, объяснение потребности, проверка менеджером и экспорт утверждённых заказов.

## Текущее состояние

Реализован этап 1: FastAPI `/health`, типизированный контракт CSV, загрузка и валидация, CLI, минимальные синтетические данные и pytest. Прогнозирование, заказы, frontend и БД пока не реализованы. Остальные пустые файлы обозначают будущие точки реализации.

## Запуск этапа 1

Нужен стандартный CPython 3.11+ (на Windows — python.org или совместимая сборка, не MSYS2). Из корня проекта в PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m backend.validate_data --input data/samples/minimal --as-of-date 2026-09-01 --history-start 2026-08-02 --history-end 2026-08-31
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

В Linux/macOS используйте `.venv/bin/python`. Если `.venv` ранее создана MSYS2, создайте отдельную `.venv-win` стандартным Python и используйте `.venv-win\Scripts\python.exe`.

В другом терминале: `Invoke-RestMethod http://127.0.0.1:8000/health`.
Ожидается HTTP 200 и `{"status":"ok","version":"0.1.0"}`. Документация API: `http://127.0.0.1:8000/docs`.

CLI печатает один JSON ValidationReport. На образце: `valid: true`, ошибок нет, ожидается предупреждение `SHORT_HISTORY` (история 30 дней). Exit code: 0 при отсутствии ошибок, 1 при ошибках данных/контекста; синтаксические ошибки аргументов обрабатывает argparse (код 2).

Файлы `data/samples/minimal/` полностью синтетические: 3 SKU, 2 категории, склад, 2 поставщика, 10 клиентов, 30 дней, stockout и частично полученная поставка. Это проверка контракта, не реалистичный обучающий набор. Реальные файлы кладите в игнорируемый каталог `data/local/`.

Контракт этапа: [docs/data-contract.md](docs/data-contract.md). Результат `load_csv_dataset()` содержит `dataset: null`, если есть хотя бы одна ошибка; частично разобранные данные не допускаются к дальнейшему использованию. Предупреждения не блокируют набор. Количества сохраняются как Decimal.

Принятый стек: Python / FastAPI / pandas / NumPy / openpyxl, PostgreSQL / SQLAlchemy / Alembic, React / TypeScript / Vite / Ant Design / Recharts. Statsmodels — для сравнения моделей прогноза. Планируемый запуск — Docker Compose.

## Структура

```text
backend/            API, бизнес-модули, расчётное ядро, доступ к данным
frontend/           интерфейс менеджера и клиент API
docs/               архитектура, контракты данных и API, план проверки
tests/              приёмочные сценарии и синтетические данные
data/               локальные загрузки и выгрузки; содержимое исключено из Git
infra/              описание будущего окружения запуска
IEK/                исходные Excel партнёра
Systeme electric/   исходные Excel партнёра
PROJECT_PLAN.md     этапы и методика проекта
```

## Документация

- [Архитектура и границы модулей](docs/ARCHITECTURE.md)
- [Контракт входных данных](docs/DATA_CONTRACT.md)
- [Сущности и связи](docs/DATA_MODEL.md)
- [Предлагаемый контракт API](docs/API_CONTRACT.md)
- [Критерии проверки](docs/TESTING.md)
- [План реализации](PROJECT_PLAN.md)
- [Backend](backend/README.md), [frontend](frontend/README.md), [окружение](infra/README.md)

Дальнейшие адаптеры Systeme Electric и ИЭК должны выдавать тот же InputDataset; они пока не реализованы. Долгосрочный стек выше описывает будущий проект: этап 1 использует только FastAPI, Pydantic, Uvicorn, а для тестов — pytest и HTTPX.

Исходные Excel сохранены на прежних местах. Новые загрузки и экспорт помещаются в `data/`. Реальные и синтетические данные должны различаться явно. Заказы не отправляются поставщикам автоматически. В расчёт допускаются только обезличенные данные клиентов.
