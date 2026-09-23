from decimal import Decimal

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.app.engine.contracts import ISODate
from backend.app.modules.calculations.local_service import LocalService, ServiceError


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CalculationRequest(StrictModel):
    warehouse_id: str | None = None
    category_id: str | None = None
    review_days: int = Field(default=7, ge=1, le=60)
    safety_days: int = Field(default=5, ge=0, le=30)
    use_stockout: bool = True
    use_outliers: bool = True
    use_seasonality: bool = True
    use_trend: bool = True


class DatasetUpload(StrictModel):
    label: str = Field(min_length=1, max_length=120)
    history_start: ISODate
    history_end: ISODate
    as_of_date: ISODate
    files: dict[str, str]


class OrderLine(StrictModel):
    recommendation_id: str
    quantity: Decimal = Field(ge=0, allow_inf_nan=False, max_digits=28, decimal_places=12)
    reason: str = Field(default="", max_length=1000)


class CreateOrder(StrictModel):
    run_id: str
    supplier_id: str
    lines: list[OrderLine] = Field(min_length=1, max_length=1000)


class UpdateOrder(StrictModel):
    expected_version: int = Field(ge=1)
    lines: list[OrderLine] = Field(min_length=1, max_length=1000)


class ApproveOrder(StrictModel):
    expected_version: int = Field(ge=1)


def create_router(service: LocalService):
    router = APIRouter(prefix="/api")

    @router.get("/bootstrap")
    def bootstrap():
        return service.bootstrap()

    @router.post("/datasets")
    def upload(body: DatasetUpload):
        try:
            return service.import_dataset(body)
        except ValueError:
            raise ServiceError("Проверьте период: остаток на дату расчёта, история заканчивается предыдущим днём")

    @router.get("/datasets/current/download")
    def download_dataset():
        return Response(service.download_dataset(), media_type="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="input-dataset.zip"'})

    @router.post("/calculations", status_code=202)
    def calculate(body: CalculationRequest):
        return service.start_calculation(body.model_dump())

    @router.get("/calculations/{run_id}")
    def calculation(run_id: str):
        return service.run(run_id)

    @router.get("/preprocessing/summary")
    def preprocessing():
        return service.preprocessing_summary()

    @router.get("/orders")
    def orders():
        return {"items": service.store.all("orders")}

    @router.post("/orders", status_code=201)
    def create_order(body: CreateOrder):
        return service.create_order(body)

    @router.get("/orders/{order_id}")
    def order(order_id: str):
        return service.order(order_id)

    @router.patch("/orders/{order_id}")
    def update(order_id: str, body: UpdateOrder):
        return service.update_order(order_id, body.expected_version, lines=body.lines)

    @router.post("/orders/{order_id}/approve")
    def approve(order_id: str, body: ApproveOrder):
        return service.update_order(order_id, body.expected_version, approve=True)

    @router.get("/orders/{order_id}/export")
    def export(order_id: str):
        content = service.export_order(order_id)
        return Response(content, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="order-{order_id}.csv"'})

    return router
