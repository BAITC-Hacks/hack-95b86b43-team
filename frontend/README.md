# Frontend

Каркас React + TypeScript + Vite. Все `.ts` и `.tsx` пустые; приложение пока не собирается.

```text
src/
  main.tsx                   будущая точка входа
  app/App.tsx                оболочка приложения
  app/routes.tsx             маршруты экранов
  pages/                     сборка экранов
  features/import-data/      загрузка и диагностика
  features/run-calculation/  параметры и статус задания
  features/review-orders/    правки и утверждение
  shared/api/client.ts       HTTP-клиент и общая обработка ошибок
  shared/ui/                 переиспользуемые элементы
  shared/types/              общие типы
public/                      статические ресурсы
tests/                       будущие проверки интерфейса
```

Экраны: `DataPage`, `CalculationPage`, `RecommendationsPage`, `ProductPage`, `OrdersPage`. Использовать Ant Design для таблиц и форм, Recharts для графиков. Точные контракты поступают из backend; расчёт количества не дублировать в браузере.

Позже добавить `package.json`, lock-файл, `index.html`, конфигурации Vite и TypeScript, стили и тестовый инструмент. Конфигурации будут созданы одновременно с рабочим приложением.
