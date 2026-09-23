from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel

from app.db.session import get_db
from app.db.models import OrderRecommendation

router = APIRouter()

class OrderApprovalSchema(BaseModel):
    recommendation_id: int
    approved_qty: float
    correction_reason: str = None

@router.post("/approve")
def approve_order_line(payload: OrderApprovalSchema, db: Session = Depends(get_db)):
    """
    Утверждение или ручная корректировка рекомендуемого количества заказа.
    """
    rec = db.query(OrderRecommendation).filter(OrderRecommendation.id == payload.recommendation_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Рекомендация не найдена")

    rec.approved_qty = payload.approved_qty
    if payload.correction_reason:
        rec.correction_reason = payload.correction_reason

    db.commit()
    db.refresh(rec)
    return {"status": "success", "id": rec.id, "approved_qty": rec.approved_qty}
