"""Inventory reads and inbound-only book adjustments.

Two physical warehouse books (leaf_balances, semi_balances) plus the live
occupation view derived from prep_occupations. Adjustments only ever ADD to a
book (delta > 0 enforced at the schema layer); there is no decrement path.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.models import (
    Ingredient, LeafBalance, PrepOccupation, PrepRun, SemiBalance,
)


def _active_occupation_sums(db: Session) -> dict[int, float]:
    rows = db.execute(
        select(PrepOccupation.ingredient_id, func.sum(PrepOccupation.qty))
        .join(PrepRun, PrepRun.id == PrepOccupation.prep_run_id)
        .where(PrepRun.status == "active")
        .group_by(PrepOccupation.ingredient_id)
    ).all()
    return {iid: float(qty) for iid, qty in rows}


def list_ledgers(db: Session) -> dict:
    occupied = _active_occupation_sums(db)
    leaf_book = {r.ingredient_id: float(r.book_qty)
                 for r in db.scalars(select(LeafBalance)).all()}
    semi_book = {r.ingredient_id: float(r.book_qty)
                 for r in db.scalars(select(SemiBalance)).all()}
    leaf, semi = [], []
    for ing in db.scalars(select(Ingredient).order_by(Ingredient.id)).all():
        base = {"ingredient_id": ing.id, "code": ing.code, "name": ing.name,
                "unit": ing.unit}
        if ing.kind == "semi":
            book = semi_book.get(ing.id, 0.0)
            # Occupation can only exist against the leaf ledger.
            semi.append({**base, "book_qty": round(book, 3),
                         "occupied_qty": 0.0, "available_qty": round(book, 3)})
        else:
            book = leaf_book.get(ing.id, 0.0)
            occ = occupied.get(ing.id, 0.0)
            leaf.append({**base, "book_qty": round(book, 3),
                         "occupied_qty": round(occ, 3),
                         "available_qty": round(book - occ, 3)})
    return {"leaf": leaf, "semi": semi}


def adjust_book(db: Session, ingredient_id: int, delta: float) -> dict:
    """Add delta (> 0) to the book matching the ingredient kind. Dispatches to
    the physical leaf_balances / semi_balances table — never both."""
    ing = db.get(Ingredient, ingredient_id)
    if ing is None:
        raise LookupError("原料不存在")
    table = SemiBalance if ing.kind == "semi" else LeafBalance
    stmt = (
        pg_insert(table)
        .values(ingredient_id=ingredient_id, book_qty=delta)
        .on_conflict_do_update(
            index_elements=[table.ingredient_id],
            set_={"book_qty": table.book_qty + delta},
        )
    )
    db.execute(stmt)
    db.commit()
    row = db.get(table, ingredient_id)
    return {"ingredient_id": ingredient_id, "kind": ing.kind,
            "delta": delta, "book_qty": round(float(row.book_qty), 3)}


def reconcile_balance_rows(db: Session) -> None:
    """Ensure every ingredient has a zero row in the book matching its kind,
    so the leaf-only occupation FK always has a referent. Idempotent."""
    leaf_ids = {r.ingredient_id for r in db.scalars(select(LeafBalance)).all()}
    semi_ids = {r.ingredient_id for r in db.scalars(select(SemiBalance)).all()}
    changed = False
    for ing in db.scalars(select(Ingredient)).all():
        if ing.kind == "semi" and ing.id not in semi_ids:
            db.add(SemiBalance(ingredient_id=ing.id, book_qty=0.0)); changed = True
        elif ing.kind == "leaf" and ing.id not in leaf_ids:
            db.add(LeafBalance(ingredient_id=ing.id, book_qty=0.0)); changed = True
    if changed:
        db.commit()
