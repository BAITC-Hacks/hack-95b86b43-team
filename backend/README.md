# Backend

Каркас Python-приложения. Все `.py` пока пустые; пакет и зависимости не установлены.

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

При реализации добавить `pyproject.toml`, lock-файл, настройку Alembic и контейнер. Версии выбрать и проверить совместно; сейчас намеренно нет фиктивных команд запуска или пустых конфигураций сборки.

Первый модуль: импорт Systeme Electric. Первый расчёт должен запускаться напрямую из теста без FastAPI и PostgreSQL.
