# Backend

Этап 1 реализован. Команды установки и запуска находятся в корневом README.

- `backend/main.py` — публичная точка входа, переэкспортирует приложение из `app/main.py`.
- `app/engine/contracts.py` — типизированный InputDataset без файловых операций и расчётов.
- `app/modules/imports/csv_loader.py` — CSV-адаптер.
- `app/modules/imports/validation.py` — связи и бизнес-ограничения.
- `app/modules/imports/schemas.py` — диагностика и результат импорта.
- `backend/validate_data.py` — CLI.
- `app/engine/preprocessing/` — подготовка продаж, дневные модели и отчёт (этап 3).
- `app/engine/outliers.py`, `stockouts.py` — причинные клиентские признаки и восстановление исторического спроса.
- `backend/preprocess_sales.py` — CLI подготовки, отдельные экспорты без изменения входных CSV.

Остальные файлы ниже — заготовки будущих этапов; БД, jobs, frontend и расчёты не подключены.

```text
app/
  main.py                 будущая сборка FastAPI
  api/router.py           подключение HTTP-маршрутов
  core/config.py          загрузка и проверка настроек
  core/security.py        идентификация и полномочия
  db/session.py           соединение и транзакции
  db/models.py            ORM-модель; разделить при росте
  db/repositories.py      доступ к данным
  engine/                 независимые расчёты
  modules/
    imports/              адаптеры, валидация, нормализация
    catalog/              справочники и политики
    calculations/         запуск и сохранение расчёта
    orders/               версии и утверждение
    exports/              файлы заказов
  jobs/worker.py          исполнитель сохраняемых заданий
migrations/versions/      будущие миграции Alembic
tests/unit/               проверки ядра
tests/integration/        API, импорт, БД, экспорт
```

В каждом бизнес-модуле `router.py` отвечает за HTTP, `schemas.py` — за транспортные контракты, `service.py` — за сценарий. В `imports/adapters/` находятся отдельные адаптеры ИЭК и Systeme Electric.

Зависимости этапа 1 определены в `pyproject.toml`; проверенные версии сохранены в `requirements-dev.lock.txt`. Для воспроизведения используйте этот файл как constraints: `python -m pip install -c requirements-dev.lock.txt -e ".[dev]"`. Alembic и контейнер пока не требуются.

Адаптеры Excel будут добавлены отдельно. Будущий расчёт должен запускаться напрямую из теста без FastAPI и PostgreSQL.
