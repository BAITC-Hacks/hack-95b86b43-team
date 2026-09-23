import asyncio
import csv
import io
from pathlib import Path

import httpx
import pytest

from backend.app.main import create_app


@pytest.fixture
def app(tmp_path):
    sample = Path(__file__).resolve().parents[1] / "data/samples/minimal"
    app = create_app(tmp_path / "runtime", sample)
    yield app
    app.state.service.executor.shutdown(wait=True)


def request(app, method, path, **kwargs):
    async def call():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, **kwargs)
    return asyncio.run(call())


def seed_run(app):
    rec = {"id": "00123|WH-1", "sku": "00123", "name": "Cable", "unit": "m", "warehouse_id": "WH-1",
           "supplier_id": "SUP-1", "supplier_name": "Supplier", "recommended_qty": 20, "moq": 10, "order_multiple": 5}
    app.state.service.store.save("runs", "run-test", {"run_id": "run-test", "status": "completed", "result": {"recommendations": [rec]}})
    return {"run_id": "run-test", "supplier_id": "SUP-1", "lines": [
        {"recommendation_id": rec["id"], "quantity": 20, "reason": ""}]}


def test_bootstrap_and_download(app):
    data = request(app, "GET", "/api/bootstrap")
    assert data.status_code == 200
    assert data.json()["dataset"]["row_counts"]["products.csv"] == 3
    assert "path" not in data.json()["dataset"]
    assert request(app, "GET", "/api/datasets/current/download").headers["content-type"] == "application/zip"


def test_real_calculation_job_on_minimal_dataset(app):
    response = request(app, "POST", "/api/calculations", json={})
    assert response.status_code == 202
    identity = response.json()["run_id"]
    app.state.service.futures[identity].result(timeout=20)
    result = request(app, "GET", f"/api/calculations/{identity}").json()
    assert result["status"] == "completed", result
    assert len(result["result"]["recommendations"]) == 3
    assert request(app, "GET", "/api/preprocessing/summary").status_code == 200


def test_order_edit_approve_export_persists(app):
    created = request(app, "POST", "/api/orders", json=seed_run(app))
    assert created.status_code == 201
    order = created.json()
    identity = order["id"]
    assert request(app, "GET", f"/api/orders/{identity}/export").status_code == 409
    changed = request(app, "PATCH", f"/api/orders/{identity}", json={"expected_version": 1,
        "lines": [{"recommendation_id": "00123|WH-1", "quantity": 25, "reason": "Плановый дополнительный расход"}]})
    assert changed.status_code == 200
    assert changed.json()["version"] == 2
    assert request(app, "POST", f"/api/orders/{identity}/approve", json={"expected_version": 1}).status_code == 409
    approved = request(app, "POST", f"/api/orders/{identity}/approve", json={"expected_version": 2})
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    exported = request(app, "GET", f"/api/orders/{identity}/export")
    assert exported.status_code == 200
    rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig")), delimiter=";"))
    assert rows[0]["sku"] == "00123" and float(rows[0]["quantity"]) == 25
    assert request(app, "PATCH", f"/api/orders/{identity}", json={"expected_version": 3,
        "lines": [{"recommendation_id": "00123|WH-1", "quantity": 20}]}).status_code == 409
    assert app.state.service.store.get("orders", identity)["lines"][0]["quantity"] == 25


@pytest.mark.parametrize("quantity,reason", [(25, ""), (23, "Причина"), (5, "Причина"), (-5, "Причина")])
def test_invalid_quantity_or_missing_reason_blocked(app, quantity, reason):
    body = seed_run(app)
    body["lines"][0].update(quantity=quantity, reason=reason)
    assert request(app, "POST", "/api/orders", json=body).status_code == 422


def test_repeated_creation_is_idempotent(app):
    body = seed_run(app)
    first = request(app, "POST", "/api/orders", json=body).json()
    second = request(app, "POST", "/api/orders", json=body).json()
    assert first["id"] == second["id"]
    assert len(request(app, "GET", "/api/orders").json()["items"]) == 1


def test_wrong_supplier_blocked(app):
    body = seed_run(app)
    body["supplier_id"] = "FOREIGN"
    assert request(app, "POST", "/api/orders", json=body).status_code == 422


def test_repeated_creation_with_different_lines_is_not_silently_ignored(app):
    body = seed_run(app)
    first = request(app, "POST", "/api/orders", json=body).json()
    run = app.state.service.run("run-test")
    extra = {**run["result"]["recommendations"][0], "id": "00456|WH-1", "sku": "00456"}
    run["result"]["recommendations"].append(extra)
    app.state.service.store.save("runs", "run-test", run)
    body["lines"].append({"recommendation_id": extra["id"], "quantity": 20})
    response = request(app, "POST", "/api/orders", json=body)
    assert response.status_code == 409
    assert len(request(app, "GET", f"/api/orders/{first['id']}").json()["lines"]) == 1


def test_exact_fraction_survives_order_approval_and_export(app):
    body = seed_run(app)
    exact = "0.123456789123"
    run = app.state.service.run("run-test")
    run["result"]["recommendations"][0].update(recommended_qty_exact=exact,
        moq_exact="0.000000000001", order_multiple_exact="0.000000000001")
    app.state.service.store.save("runs", "run-test", run)
    body["lines"][0]["quantity"] = exact
    created = request(app, "POST", "/api/orders", json=body)
    assert created.status_code == 201, created.text
    identity = created.json()["id"]
    assert request(app, "POST", f"/api/orders/{identity}/approve", json={"expected_version": 1}).status_code == 200
    exported = request(app, "GET", f"/api/orders/{identity}/export")
    rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig")), delimiter=";"))
    assert rows[0]["quantity"] == rows[0]["recommended_qty"] == exact


def upload_body():
    sample = Path(__file__).resolve().parents[1] / "data/samples/minimal"
    return {"label": "Imported CSV", "history_start": "2026-08-02", "history_end": "2026-08-31", "as_of_date": "2026-09-01",
            "files": {p.name: p.read_text(encoding="utf-8") for p in sample.glob("*.csv")}}


def test_valid_import_activates_and_invalid_does_not(app):
    body = upload_body()
    accepted = request(app, "POST", "/api/datasets", json=body)
    assert accepted.status_code == 200 and accepted.json()["valid"]
    identity = accepted.json()["dataset"]["id"]
    body["files"]["sales.csv"] = "wrong,column\n1,2\n"
    rejected = request(app, "POST", "/api/datasets", json=body)
    assert not rejected.json()["valid"]
    assert request(app, "GET", "/api/bootstrap").json()["dataset"]["id"] == identity


def test_upload_rejects_arbitrary_paths(app):
    body = upload_body()
    body["files"]["../evil.csv"] = "bad"
    assert request(app, "POST", "/api/datasets", json=body).status_code == 422


def test_unknown_resources_and_bounded_options(app):
    assert request(app, "GET", "/api/orders/missing").status_code == 404
    assert request(app, "GET", "/api/calculations/missing").status_code == 404
    assert request(app, "POST", "/api/calculations", json={"review_days": -1}).status_code == 422
