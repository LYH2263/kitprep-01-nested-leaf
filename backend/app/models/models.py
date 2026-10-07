from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class Dish(Base):
    __tablename__ = "dishes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    portion_unit: Mapped[str] = mapped_column(String(16), default="份")

class Ingredient(Base):
    """Master data only. Stock lives in two physically separate ledger tables
    (leaf_balances / semi_balances) — never one table filtered by kind."""
    __tablename__ = "ingredients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    unit: Mapped[str] = mapped_column(String(16), default="kg")
    kind: Mapped[str] = mapped_column(String(8), default="leaf")  # 'leaf' | 'semi'
    __table_args__ = (CheckConstraint("kind in ('leaf', 'semi')", name="ck_ing_kind"),)

class LeafBalance(Base):
    """叶料仓账面 — book balance of the leaf/raw-material warehouse.
    Written only by inbound adjustments; prep generation never updates it."""
    __tablename__ = "leaf_balances"
    ingredient_id: Mapped[int] = mapped_column(
        ForeignKey("ingredients.id", ondelete="CASCADE"), primary_key=True)
    book_qty: Mapped[float] = mapped_column(Float, default=0.0)

class SemiBalance(Base):
    """半成品仓账面 — book balance of the semi-finished warehouse.
    Written only by inbound adjustments; prep generation never reads or locks it."""
    __tablename__ = "semi_balances"
    ingredient_id: Mapped[int] = mapped_column(
        ForeignKey("ingredients.id", ondelete="CASCADE"), primary_key=True)
    book_qty: Mapped[float] = mapped_column(Float, default=0.0)

class BomLine(Base):
    """One BOM edge. Parent is exactly one of a dish or a semi ingredient;
    child may be a leaf or a semi ingredient (enables multi-level trees)."""
    __tablename__ = "bom_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dish_id: Mapped[int | None] = mapped_column(ForeignKey("dishes.id"), nullable=True)
    parent_ingredient_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingredients.id"), nullable=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"))  # child
    qty_per_portion: Mapped[float] = mapped_column(Float)
    __table_args__ = (
        CheckConstraint(
            "(dish_id IS NOT NULL AND parent_ingredient_id IS NULL) "
            "OR (dish_id IS NULL AND parent_ingredient_id IS NOT NULL)",
            name="ck_bomline_one_parent"),
    )

class KitchenOrder(Base):
    __tablename__ = "kitchen_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    outlet: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="open")

class OrderLine(Base):
    __tablename__ = "order_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("kitchen_orders.id"))
    dish_id: Mapped[int] = mapped_column(ForeignKey("dishes.id"))
    portions: Mapped[int] = mapped_column(Integer)

class PrepRun(Base):
    __tablename__ = "prep_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("kitchen_orders.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    # 'active' | 'superseded'; NULL = immutable legacy snapshot, never updated.
    status: Mapped[str | None] = mapped_column(String(16), nullable=True, default="active")

class PrepOccupation(Base):
    """备料占用 — the third ledger. FK targets leaf_balances (not ingredients),
    so a semi id has no referent and an occupation against the semi warehouse
    fails at the database boundary and rolls back the whole generation."""
    __tablename__ = "prep_occupations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prep_run_id: Mapped[int] = mapped_column(
        ForeignKey("prep_runs.id", ondelete="CASCADE"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("kitchen_orders.id"), index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("leaf_balances.ingredient_id"))
    qty: Mapped[float] = mapped_column(Float)
    __table_args__ = (
        UniqueConstraint("prep_run_id", "ingredient_id", name="uq_occ_run_ing"),
        Index("ix_occ_ingredient", "ingredient_id"),
    )
