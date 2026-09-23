# Backend

Первый рабочий этап: чтение и полный аудит Excel обоих поставщиков, базовый прогноз,
независимый расчёт потребности и диагностическая таблица Systeme Electric.
Реализованы PostgreSQL-хранилище импорта, миграции Alembic, диагностика строк и неизменяемые наборы данных.
API, worker и процесс утверждения пока не реализованы.

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

## Запуск

Python 3.12+. Все команды ниже выполнять из `backend/`.

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m app.cli profile
.venv/Scripts/python -m app.cli preview-systeme --policy ../tests/fixtures/synthetic/systeme_preview_policy.json
.venv/Scripts/python -m unittest discover -s tests/unit -v
.venv/Scripts/python -m unittest discover -s tests/integration -v
```

В Linux после создания окружения использовать `.venv/bin/python` вместо `.venv/Scripts/python`.
`pyproject.toml` описывает пакет; `requirements.txt` фиксирует прямые runtime-зависимости.
Первый расчёт проверен на Python 3.12.14; слой PostgreSQL и полный набор тестов — на Python 3.14.7
в пользовательском `.venv`. Тесты используют стандартный unittest.

Если Python отсутствует в PATH, можно передать абсолютный путь к доступному интерпретатору.
Для первого аудита использован встроенный интерпретатор; зависимости PostgreSQL установлены
в локальное `backend/.venv`. Глобальное окружение не менялось.

## Результаты

- `data/cache/profile/profile.json`: полный профиль 12 книг, сверки и ошибки.
- `data/cache/profile/*-v1.jsonl`: диагностическое представление строк с файлом, SHA-256, листом и номером строки.
- `data/cache/systeme-preview.json`: вычисления, происхождение входов и все допущения.
- `data/cache/systeme-preview.html`: открываемая в браузере таблица с обоснованием каждой строки.

Пути результатов считаются от корня репозитория. Можно указать `--root` и `--output`.
Повторный аудит пишет в тот же файл по хешу и версии адаптера; отдельные дубли не создаются.
Это временная диагностика, не активация набора данных и не хранилище PostgreSQL.
Весь `data/cache/` исключён из Git. Исходные Excel открываются только для чтения.

## Ограничения первого расчёта

Политика сценария явно предполагает дату снимка 22.09.2026, совместимый общий охват,
срок 14 дней, пересмотр 7 дней, страховой запас на 7 дней, пересчёт единиц 1:1 и отсутствие
отдельного MOQ. Приоритет кратности задан отдельному файлу MOQ. Это не подтверждённые условия закупок.

Прогноз — медиана суточных темпов за последние шесть полных календарных месяцев.
Пустая или отрицательная история требует проверки; она не заполняется нулями и не превращается в модуль числа.
Частичный сентябрь и будущие месяцы исключены. Сезонность, тренд, выбросы и stockout ещё не реализованы.
Страховой запас на дни спроса — допущение демонстрации, не завершённая модель ошибки прогноза.

Горизонт охватывает `[дата расчёта, дата расчёта + L + R)`.
Остаток считается входящим на начало дня, поступления приходят до спроса этого дня.
Поступления после горизонта, просроченные и неподтверждённые не уменьшают потребность.
Обычная новая поставка ожидается на дату расчёта + L; более ранний дефицит требует ускорения.
Свободный остаток используется напрямую, резерв повторно не вычитается.

Архитектурные границы сохраняются: `engine/` не импортирует Excel, HTTP или базу;
`modules/imports/` читает и проверяет источники; `modules/calculations/preview.py` связывает первый сценарий.

## PostgreSQL: загрузка и версии данных

Подробный сценарий — [docs/POSTGRES_IMPORT.md](../docs/POSTGRES_IMPORT.md).
На текущей машине база уже запущена, миграции применены, 12 книг импортированы.
Секрет подключения хранится в корневом `.env`, исключённом из Git.

Для новой машины: заполнить корневой `.env` по `.env.example`, затем из корня:

```powershell
docker compose up -d postgres
```

Из `backend/`:

```powershell
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m app.cli db-upgrade
.venv/Scripts/python -m app.cli import-all
.venv/Scripts/python -m app.cli imports
```

`import-all` можно повторять: неизменённые файлы и контекст получают `reused: true`.
Для текущей локальной базы готов явный сценарный манифест:

```powershell
.venv/Scripts/python -m app.cli dataset-create ../data/cache/systeme-dataset-manifest.json
.venv/Scripts/python -m app.cli preview-systeme --policy ../tests/fixtures/synthetic/systeme_preview_policy.json --dataset 4e124f3e-22c3-4a6f-a798-b737cf075e25 --output ../data/cache/systeme-db-preview.json
```

UUID выше относится только к текущей локальной базе. На новой машине использовать ID,
выданный `dataset-create`; пример манифеста и описание полей есть в документации.
Режим `--dataset` читает сохранённые `NUMERIC` и строки из PostgreSQL, не открывая Excel.
Результат включает ID набора; исходный файловый сценарий без `--dataset` сохранён.

Тесты PostgreSQL запускаются отдельно и создают временную схему `test_import_<uuid>`:

```powershell
$env:RUN_POSTGRES_TESTS = '1'
.venv/Scripts/python -m unittest discover -s tests/integration -v
```

Рабочие таблицы не очищаются. Тестовая схема удаляется после проверки.
Проверены откат частичной записи, повтор/конкуренция, точность количеств,
исключение дублей, неизменность версий, upgrade/downgrade миграций и совпадение расчёта с Excel.

Дальше: полноценные алгоритмы пяти must-have, каталог товаров/единиц,
согласование вопросов [аудита](../docs/DATA_AUDIT.md), затем API и worker.
