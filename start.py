from __future__ import annotations

import json
import mimetypes
import os
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT / "frontend"
DIST_DIR = FRONTEND_DIR / "dist"
HOST = "127.0.0.1"
PORT = 4173


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str | None = None, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self):
        if self.path.startswith("/api/"):
            self.handle_api()
            return

        if self.path in ("/", ""):
            target = DIST_DIR / "index.html"
            self.serve_file(target)
            return

        normalized = self.path.split("?", 1)[0]
        relative = normalized.lstrip("/")
        if not relative:
            self.serve_file(DIST_DIR / "index.html")
            return

        candidate = (DIST_DIR / relative).resolve()
        try:
            candidate.relative_to(DIST_DIR.resolve())
        except ValueError:
            self.send_error(403, "Forbidden")
            return

        if candidate.is_file():
            self.serve_file(candidate)
            return

        self.serve_file(DIST_DIR / "index.html")

    def handle_api(self):
        payload = {"status": "ok", "project": "Systeme Planning", "mode": "single-process"}
        route = self.path.split("?", 1)[0]

        if route == "/api/health":
            payload = {"status": "ok", "project": "Systeme Planning", "service": "healthy"}
        elif route == "/api/dashboard":
            payload = {
                "kpis": [
                    {"label": "Покрытие", "value": "96%", "note": "+4.2% за 7 дней"},
                    {"label": "Критические позиции", "value": "12", "note": "Из 148 SKU"},
                    {"label": "Прогноз спроса", "value": "18.4k", "note": "На 14 дней"},
                    {"label": "Подтверждено заявок", "value": "84%", "note": "6 заявок в работе"},
                ],
                "recommendations": [
                    {"code": "S-1048", "article": "Кабель 3x2.5", "demand": 420, "incoming": 180, "order": 260, "risk": "Высокий", "status": "Дефицит"},
                    {"code": "S-2041", "article": "Коробка распаечная", "demand": 310, "incoming": 140, "order": 210, "risk": "Средний", "status": "Проверка"},
                    {"code": "S-3079", "article": "DIN-рейка 12 мод.", "demand": 680, "incoming": 420, "order": 280, "risk": "Низкий", "status": "Готово"},
                ],
            }
        else:
            payload = {"status": "not_found", "route": route}
            self.send_response(404)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def serve_file(self, file_path: Path):
        if not file_path.exists():
            self.send_error(404, "File not found")
            return

        mime_type, _ = mimetypes.guess_type(str(file_path))
        if mime_type is None:
            mime_type = "application/octet-stream"

        try:
            data = file_path.read_bytes()
        except OSError:
            self.send_error(500, "Read error")
            return

        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    if not DIST_DIR.exists():
        raise SystemExit(
            "Frontend build not found. Run: cd frontend && npm install && npm run build"
        )

    os.chdir(ROOT)
    server = ThreadingHTTPServer((HOST, PORT), lambda *args, **kwargs: AppHandler(*args, directory=str(DIST_DIR), **kwargs))
    url = f"http://{HOST}:{PORT}"

    def open_browser():
        webbrowser.open(url)

    threading.Timer(0.6, open_browser).start()

    print(f"Systeme Planning is running at {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
