from sqlalchemy import Column, String, Float, Integer, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.session import Base

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    code_1c = Column(String, unique=True, index=True, nullable=False)  # Сохраняет ведущие нули
    vendor_code = Column(String, index=True)
    name = Column(String, nullable=False)
    supplier = Column(String, index=True, nullable=False)  # "Systeme Electric" или "IEK"
    category = Column(String, index=True)
    storage_unit = Column(String, default="шт")
    order_unit = Column(String, default="шт")
    conversion_factor = Column(Float, default=1.0)  # Пересчёт (например, бухта -> метр)
    moq = Column(Float, default=1.0)
    multiplicity = Column(Float, default=1.0)

class InventorySnapshot(Base):
    __tablename__ = "inventory_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    product_code_1c = Column(String, ForeignKey("products.code_1c"), nullable=False)
    snapshot_date = Column(DateTime, nullable=False)
    warehouse = Column(String, default="ALL")
    total_stock = Column(Float, default=0.0)
    reserved_stock = Column(Float, default=0.0)
    free_stock = Column(Float, default=0.0)

class InboundShipment(Base):
    __tablename__ = "inbound_shipments"

    id = Column(Integer, primary_key=True, index=True)
    product_code_1c = Column(String, ForeignKey("products.code_1c"), nullable=False)
    expected_date = Column(DateTime, nullable=False)
    quantity = Column(Float, nullable=False)
    warehouse = Column(String, default="ALL")

class CalculationRun(Base):
    __tablename__ = "calculation_runs"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    supplier = Column(String, nullable=False)
    warehouse = Column(String, default="ALL")
    lead_time_days = Column(Integer, default=14)
    review_period_days = Column(Integer, default=7)
    status = Column(String, default="COMPLETED")  # IN_PROGRESS, COMPLETED, FAILED

    recommendations = relationship("OrderRecommendation", back_populates="run")

class OrderRecommendation(Base):
    __tablename__ = "order_recommendations"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("calculation_runs.id"), nullable=False)
    product_code_1c = Column(String, ForeignKey("products.code_1c"), nullable=False)

    current_stock = Column(Float, default=0.0)
    in_transit_stock = Column(Float, default=0.0)
    forecasted_demand = Column(Float, default=0.0)
    safety_stock = Column(Float, default=0.0)

    calculated_need = Column(Float, default=0.0)       # Чистая потребность до округления
    recommended_qty = Column(Float, default=0.0)        # С учётом MOQ и кратности
    approved_qty = Column(Float, nullable=True)         # Скорректированное менеджером кол-во
    is_urgent = Column(Boolean, default=False)          # Риск дефицита до прихода поставки

    explanation_json = Column(Text, nullable=False)     # Шаговое математическое обоснование
    correction_reason = Column(String, nullable=True)

    run = relationship("CalculationRun", back_populates="recommendations")
