from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from contextlib import asynccontextmanager

from backend import __version__
from backend.app.engine.contracts import DatasetContext
from backend.app.modules.imports.csv_loader import validate_directory
from backend.app.modules.imports.schemas import ValidationReport
from backend.app.api.runtime_api import create_router
from backend.app.modules.calculations.local_service import LocalService, ServiceError


def create_app(runtime_dir: Path | None = None, initial_dataset: Path | None = None) -> FastAPI:
    root = Path(__file__).resolve().parents[2]
    service = LocalService(runtime_dir or root / "data" / "runtime", initial_dataset)

    @asynccontextmanager
    async def lifespan(app):
        yield
        service.executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="HACKALEM procurement", version=__version__, lifespan=lifespan)
    app.state.service = service
    app.include_router(create_router(service))

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError):
        return JSONResponse(status_code=exc.status, content={"detail": exc.message})

    @app.middleware("http")
    async def request_limits(request: Request, call_next):
        if request.method in {"POST", "PATCH"}:
            size = request.headers.get("content-length", "0")
            if not size.isdigit() or int(size) > 30_000_000:
                return JSONResponse(status_code=413, content={"detail": "Слишком большой запрос (максимум 30 МБ)"})
        return await call_next(request)

    frontend = root / "frontend" / "dist"
    if (frontend / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon():
        return FileResponse(root / "frontend" / "public" / "favicon.svg", media_type="image/svg+xml")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def home():
        if (frontend / "index.html").is_file():
            return FileResponse(frontend / "index.html")
        return """<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Контур закупок — запуск</title>
<style>body{font:17px/1.6 system-ui;background:#f3f6fa;color:#172638;margin:0;padding:6vw}
main{max-width:760px;margin:auto;background:white;padding:36px;border-radius:18px}
a{color:#1557b0}li{margin:14px 0}.badge{color:#17663f}code{background:#eef2f7;padding:3px 6px}</style>
<main><p class="badge">● Backend работает</p><h1>Контур закупок</h1>
<p>Интерфейс ещё не собран. Выполните <code>.\\setup.ps1</code>, затем перезапустите сервер.</p>
<ul><li><a href="/docs">Открыть API и выполнить запросы</a></li>
<li><a href="/data/sample/validation">Проверить демонстрационный набор CSV</a></li>
<li><a href="/health">Проверить состояние сервера</a></li></ul>
<p>Демонстрационный набор: 3 товара, 30 дней, 10 обезличенных клиентов.
Предупреждение SHORT_HISTORY ожидаемо: история короче двух лет.</p>
<p>Расчёт и управление заказами доступны через API. Сборка интерфейса находится в frontend/dist.</p>
<p>Для запуска используйте <code>.\\start.ps1</code>. Повторный запуск распознаёт работающий API.</p>
</main></html>"""

    @app.get("/data/sample/validation", response_model=ValidationReport)
    def validate_sample() -> ValidationReport:
        sample = Path(__file__).resolve().parents[2] / "data" / "samples" / "minimal"
        context = DatasetContext(as_of_date="2026-09-01", history_start="2026-08-02", history_end="2026-08-31")
        return validate_directory(sample, context)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
