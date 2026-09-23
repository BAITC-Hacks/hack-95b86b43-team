"""Local MVP orchestration. Models and engine stay independent of HTTP/storage."""

import csv
import hashlib
import io
import json
import threading
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from backend.app.core.store import Store
from backend.app.engine.contracts import DatasetContext
from backend.app.engine.preprocessing.report import generate_preprocessing_report
from backend.app.engine.preprocessing.sales_cleaning import prepare_sales
from backend.app.modules.imports.csv_loader import TABLE_MODELS, load_csv_dataset


ROOT = Path(__file__).resolve().parents[4]
CSV_FILES = tuple(f"{name}.csv" for name in TABLE_MODELS)


def now():
    return datetime.now(timezone.utc).isoformat()


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 422):
        self.message, self.status = message, status


class LocalService:
    def __init__(self, runtime: Path, initial_dataset: Path | None = None):
        self.runtime = runtime
        self.store = Store(runtime)
        self.initial_dataset = initial_dataset
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="calculation")
        self.lock = threading.RLock()
        self.prepared_cache = None
        self.futures = {}
        for run in self.store.all("runs"):
            if run["status"] in {"queued", "running"}:
                run.update(status="failed", message="Сервер был перезапущен. Запустите расчёт заново.",
                           error="Расчёт прерван перезапуском", progress=0)
                self.store.save("runs", run["run_id"], run)

    def dataset_info(self):
        with self.lock:
            current = self.store.get_setting("dataset")
            if current:
                return current
            directory = self.initial_dataset or ROOT / "data" / "synthetic"
            if not (directory / "products.csv").exists():
                if self.initial_dataset:
                    raise ServiceError("Нет входных CSV", 404)
                from backend.synthetic.generator import generate_dataset
                generate_dataset(directory)
            context = DatasetContext(as_of_date="2026-09-01", history_start="2024-09-01", history_end="2026-08-31")
            # The tiny contract fixture is supported by test/demo setup without metadata access.
            if self.initial_dataset:
                context = DatasetContext(as_of_date="2026-09-01", history_start="2026-08-02", history_end="2026-08-31")
            loaded = load_csv_dataset(directory, context)
            if not loaded.report.valid:
                raise ServiceError("Демонстрационные CSV не прошли проверку. Перегенерируйте набор или импортируйте данные.")
            current = self._manifest("synthetic", "Демонстрационный набор · 120 SKU" if not self.initial_dataset else "Минимальный набор", directory,
                                     context, loaded.report, synthetic=True)
            self.store.set_setting("dataset", current)
            return current

    @staticmethod
    def _manifest(identity, label, directory, context, report, synthetic=False):
        return {"id": identity, "label": label, "synthetic": synthetic, "path": str(directory.resolve()),
                **context.model_dump(mode="json"), "row_counts": report.row_counts,
                "warnings": [w.model_dump(mode="json") for w in report.warnings]}

    def bootstrap(self):
        manifest = self.dataset_info()
        loaded = load_csv_dataset(manifest["path"], DatasetContext(**{k: manifest[k] for k in ("as_of_date", "history_start", "history_end")}))
        if not loaded.report.valid:
            raise ServiceError("Файлы активного набора изменены и не проходят проверку.")
        data = loaded.dataset
        public = {k: v for k, v in manifest.items() if k != "path"}
        return {"dataset": public,
                "warehouses": [r.model_dump(exclude={"source_file", "source_row"}) for r in data.warehouses],
                "categories": [r.model_dump(exclude={"source_file", "source_row"}) for r in data.categories],
                "suppliers": [r.model_dump(exclude={"source_file", "source_row"}) for r in data.suppliers],
                "runs": [{k: r.get(k) for k in ("run_id", "status", "created_at", "message", "dataset_id")} for r in self.store.all("runs")[:10]],
                "orders": self.store.all("orders")}

    def import_dataset(self, request):
        if set(request.files) != set(CSV_FILES):
            raise ServiceError("Нужны ровно 9 CSV: " + ", ".join(CSV_FILES))
        if sum(len(value.encode("utf-8")) for value in request.files.values()) > 25_000_000:
            raise ServiceError("Максимальный размер CSV-набора — 25 МБ", 413)
        identity = uuid.uuid4().hex
        directory = self.runtime / "datasets" / identity
        directory.mkdir(parents=True)
        for name, content in request.files.items():
            (directory / name).write_text(content, encoding="utf-8", newline="")
        context = DatasetContext(as_of_date=request.as_of_date, history_start=request.history_start, history_end=request.history_end)
        loaded = load_csv_dataset(directory, context)
        report = loaded.report.model_dump(mode="json")
        if not loaded.report.valid:
            return {"valid": False, "report": report}
        manifest = self._manifest(identity, request.label, directory, context, loaded.report)
        with self.lock:
            self.store.set_setting("dataset", manifest)
        return {"valid": True, "dataset": {k: v for k, v in manifest.items() if k != "path"}, "report": report}

    def download_dataset(self):
        manifest = self.dataset_info()
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for filename in CSV_FILES:
                archive.write(Path(manifest["path"]) / filename, filename)
        return output.getvalue()

    def start_calculation(self, options):
        manifest = self.dataset_info()
        run_id = uuid.uuid4().hex
        snapshot = self.runtime / "runs" / run_id / "input"
        snapshot.mkdir(parents=True)
        digest = hashlib.sha256()
        for name in CSV_FILES:
            content = (Path(manifest["path"]) / name).read_bytes()
            digest.update(name.encode())
            digest.update(content)
            (snapshot / name).write_bytes(content)
        digest.update(json.dumps({k: manifest[k] for k in ("as_of_date", "history_start", "history_end")}, sort_keys=True).encode())
        run = {"run_id": run_id, "status": "queued", "progress": 0, "message": "В очереди на расчёт",
               "created_at": now(), "dataset_id": manifest["id"], "dataset_label": manifest["label"],
               "synthetic": manifest["synthetic"], "options": options, "input_digest": digest.hexdigest(),
               "context": {k: manifest[k] for k in ("as_of_date", "history_start", "history_end")}}
        self.store.save("runs", run_id, run)
        self.futures[run_id] = self.executor.submit(self._calculate, run, snapshot)
        return {"run_id": run_id, "status": "queued"}

    def _calculate(self, run, snapshot):
        try:
            run.update(status="running", progress=10, message="Проверяем данные")
            self.store.save("runs", run["run_id"], run)
            loaded = load_csv_dataset(snapshot, DatasetContext(**run["context"]))
            if not loaded.report.valid:
                raise ServiceError("Входные данные не прошли проверку")
            dataset = loaded.dataset
            if run["options"].get("warehouse_id") and run["options"]["warehouse_id"] not in {w.warehouse_id for w in dataset.warehouses}:
                raise ServiceError("Неизвестный склад")
            if run["options"].get("category_id") and run["options"]["category_id"] not in {c.category_id for c in dataset.categories}:
                raise ServiceError("Неизвестная категория")
            run.update(progress=25, message="Восстанавливаем спрос и проверяем клиентские события")
            self.store.save("runs", run["run_id"], run)
            if self.prepared_cache and self.prepared_cache[0] == run["input_digest"]:
                prepared = self.prepared_cache[1]
            else:
                prepared = prepare_sales(dataset)
                self.prepared_cache = (run["input_digest"], prepared)
            run.update(progress=70, message="Сезонность, тренд и календарь поставок")
            self.store.save("runs", run["run_id"], run)
            from backend.app.engine.replenishment import calculate_recommendations
            result = calculate_recommendations(dataset, prepared, **run["options"])
            result["preprocessing"] = generate_preprocessing_report(prepared)
            result["dataset"] = {"id": run["dataset_id"], "label": run["dataset_label"], "synthetic": run["synthetic"], **run["context"]}
            run.update(status="completed", progress=100, message="Расчёт готов", result=result, completed_at=now())
        except Exception as exc:
            # Keep a local diagnostic while returning a bounded, non-sensitive error to UI.
            (snapshot.parent / "error.txt").write_text(f"{type(exc).__name__}: {exc}", encoding="utf-8")
            run.update(status="failed", progress=0, message="Не удалось завершить расчёт",
                       error=exc.message if isinstance(exc, ServiceError) else "Ошибка расчётного модуля. Подробности сохранены локально в runs.")
        self.store.save("runs", run["run_id"], run)

    def run(self, identity):
        result = self.store.get("runs", identity)
        if result is None:
            raise ServiceError("Расчёт не найден", 404)
        return result

    def preprocessing_summary(self):
        for run in self.store.all("runs"):
            if run["status"] == "completed":
                return run["result"]["preprocessing"]
        raise ServiceError("Сначала выполните расчёт", 404)

    def _order_lines(self, run, supplier_id, submitted):
        recommendations = {r["id"]: r for r in run["result"]["recommendations"]}
        lines, seen = [], set()
        for requested in submitted:
            rec = recommendations.get(requested.recommendation_id)
            if rec is None or rec["supplier_id"] != supplier_id or rec["id"] in seen:
                raise ServiceError("Позиции должны быть уникальны и принадлежать выбранному поставщику")
            seen.add(rec["id"])
            qty = requested.quantity
            suggested = Decimal(str(rec.get("recommended_qty_exact", rec["recommended_qty"])))
            multiple = Decimal(str(rec.get("order_multiple_exact") or rec.get("order_multiple") or "1"))
            moq = Decimal(str(rec.get("moq_exact") or rec.get("moq") or "0"))
            if qty > 0 and (qty < moq or qty % multiple != 0):
                raise ServiceError(f"{rec['sku']}: количество должно быть не меньше MOQ {moq} и кратно {multiple}")
            if qty != suggested and len(requested.reason.strip()) < 3:
                raise ServiceError(f"{rec['sku']}: укажите причину изменения количества")
            lines.append({"recommendation_id": rec["id"], "sku": rec["sku"], "name": rec["name"],
                          "warehouse_id": rec["warehouse_id"], "unit": rec["unit"], "recommended_qty": float(suggested),
                          "quantity": float(qty), "reason": requested.reason.strip(), "moq": float(moq),
                          "order_multiple": float(multiple), "quantity_exact": format(qty, "f"),
                          "recommended_qty_exact": format(suggested, "f")})
        if not lines:
            raise ServiceError("Заказ должен содержать хотя бы одну позицию")
        return lines

    def create_order(self, request):
        run = self.run(request.run_id)
        if run["status"] != "completed":
            raise ServiceError("Расчёт ещё не готов", 409)
        lines = self._order_lines(run, request.supplier_id, request.lines)
        with self.lock:
            for old in self.store.all("orders"):
                if old["run_id"] == request.run_id and old["supplier_id"] == request.supplier_id:
                    def signature(items):
                        return sorted((item["recommendation_id"],
                                       Decimal(str(item.get("quantity_exact", item["quantity"]))),
                                       item["reason"]) for item in items)
                    if signature(old["lines"]) != signature(lines):
                        raise ServiceError("Для этого поставщика уже создан заказ с другим составом или количеством. "
                                           "Откройте его во вкладке «Заказы»; для нового заказа выполните новый расчёт.", 409)
                    return old  # Identical clicks never create duplicate supplier orders.
            rec = next(r for r in run["result"]["recommendations"] if r["supplier_id"] == request.supplier_id)
            order = {"id": uuid.uuid4().hex, "run_id": request.run_id, "supplier_id": request.supplier_id,
                     "supplier_name": rec["supplier_name"], "status": "draft", "version": 1,
                     "created_at": now(), "lines": lines, "audit": [{"action": "created", "at": now()}]}
            self.store.save("orders", order["id"], order)
            return order

    def order(self, identity):
        order = self.store.get("orders", identity)
        if order is None:
            raise ServiceError("Заказ не найден", 404)
        return order

    def update_order(self, identity, version, lines=None, approve=False):
        with self.lock:
            order = self.order(identity)
            if order["version"] != version:
                raise ServiceError("Заказ изменён в другой вкладке. Обновите данные.", 409)
            if order["status"] == "approved":
                raise ServiceError("Утверждённый заказ неизменяем. Создайте новый расчёт.", 409)
            if lines is not None:
                order["lines"] = self._order_lines(self.run(order["run_id"]), order["supplier_id"], lines)
            if approve:
                if not any(line["quantity"] > 0 for line in order["lines"]):
                    raise ServiceError("Нельзя утвердить заказ с нулевым количеством по всем позициям")
                order.update(status="approved", approved_at=now())
            order["version"] += 1
            order["audit"].append({"action": "approved" if approve else "edited", "at": now(), "version": order["version"],
                                   "lines": order["lines"]})
            if not self.store.replace_order(order, version):
                raise ServiceError("Заказ изменён в другой вкладке. Обновите данные.", 409)
            return order

    def export_order(self, identity):
        order = self.order(identity)
        if order["status"] != "approved":
            raise ServiceError("Экспорт доступен после утверждения", 409)
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, delimiter=";", lineterminator="\r\n")
        writer.writerow(["order_id", "supplier_id", "sku", "warehouse_id", "unit", "quantity", "recommended_qty", "reason", "approved_at"])
        def safe(value):
            text = str(value)
            return "'" + text if text.startswith(("=", "+", "-", "@")) else text
        for line in order["lines"]:
            if line["quantity"] > 0:
                writer.writerow([safe(v) for v in (order["id"], order["supplier_id"], line["sku"], line["warehouse_id"],
                    line["unit"], line.get("quantity_exact", line["quantity"]),
                    line.get("recommended_qty_exact", line["recommended_qty"]), line["reason"], order["approved_at"])])
        return stream.getvalue().encode("utf-8-sig")
