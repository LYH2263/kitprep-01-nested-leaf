"""Transactional prep generation.

One generation = one transaction with a strict lock hierarchy:

  1. kitchen_orders row FOR UPDATE        (serializes double-clicks per order)
  2. structural validation (cycle / empty semi) BEFORE any ledger write
  3. leaf_balances rows FOR UPDATE, ascending id
       — semi_balances is never read or locked, so a concurrent change of the
         semi-finished book cannot affect or block a generation
  4. supersede this order's previous active run, insert new run + occupations
  5. single commit; any exception rolls all three ledgers back together

Occupations reference leaf_balances by FK, making it physically impossible to
occupy the semi warehouse.
"""
from __future__ import annotations
import json
from datetime import datetime

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.models.models import (
    BomLine, Ingredient, KitchenOrder, LeafBalance, OrderLine,
    PrepOccupation, PrepRun,
)
from app.services.bom_engine import build_result, explode_to_leaves

# Bounded wait on contended rows -> API returns 409 instead of blocking forever.
# Tests may monkeypatch this upward when deliberately holding locks.
LOCK_TIMEOUT_MS = 3000


def _set_lock_timeout(db: Session) -> None:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT_MS}', true)"))


def _order_info(order: KitchenOrder) -> dict:
    return {"id": order.id, "code": order.code, "outlet": order.outlet}


def empty_payload(order: KitchenOrder) -> dict:
    return {
        "id": None, "order_id": order.id, "status": None, "legacy": False,
        "order": _order_info(order), "version": 2,
        "prep_lines": [], "shortages": [],
        "stats": {"ingredient_count": 0, "shortage_count": 0,
                  "total_shortage_qty": 0, "total_need_qty": 0},
    }


def run_payload(run: PrepRun) -> dict:
    data = json.loads(run.result_json or "{}")
    legacy = "version" not in data
    return {
        "id": run.id,
        "order_id": run.order_id,
        "status": run.status,
        "legacy": legacy,
        "created_at": run.created_at,
        **data,
    }


def generate_prep(db: Session, order_id: int, *, after_locks=None) -> dict:
    # 1. order row lock — always acquired first
    _set_lock_timeout(db)
    order = db.scalars(
        select(KitchenOrder).where(KitchenOrder.id == order_id).with_for_update()
    ).one_or_none()
    if order is None:
        raise LookupError("订单不存在")

    order_lines = [{"dish_id": l.dish_id, "portions": l.portions}
                   for l in db.scalars(
                       select(OrderLine).where(OrderLine.order_id == order_id)).all()]
    all_bom = db.scalars(select(BomLine)).all()
    dish_lines = [{"dish_id": b.dish_id, "ingredient_id": b.ingredient_id,
                   "qty_per_portion": b.qty_per_portion}
                  for b in all_bom if b.dish_id is not None]
    semi_lines = [{"parent_ingredient_id": b.parent_ingredient_id,
                   "ingredient_id": b.ingredient_id,
                   "qty_per_portion": b.qty_per_portion}
                  for b in all_bom if b.parent_ingredient_id is not None]
    ingredients = {i.id: {"code": i.code, "name": i.name, "unit": i.unit, "kind": i.kind}
                   for i in db.scalars(select(Ingredient)).all()}

    # 2. structural validation happens here, before touching any ledger;
    #    build_result will validate again once books are known.
    need = explode_to_leaves(order_lines, dish_lines, semi_lines, ingredients)
    leaf_ids = sorted(need)

    # 3. leaf ledger locks, ascending id (missing zero rows created first).
    #    semi_balances is deliberately absent.
    existing = {r.ingredient_id: r
                for r in db.scalars(
                    select(LeafBalance).where(LeafBalance.ingredient_id.in_(leaf_ids)))}
    for iid in leaf_ids:
        if iid not in existing:
            db.add(LeafBalance(ingredient_id=iid, book_qty=0.0))
    if any(iid not in existing for iid in leaf_ids):
        db.flush()
    leaf_book: dict[int, float] = {}
    for iid in leaf_ids:
        row = db.scalars(
            select(LeafBalance).where(LeafBalance.ingredient_id == iid)
            .with_for_update()
        ).one()
        leaf_book[iid] = float(row.book_qty)

    if after_locks is not None:
        after_locks()

    # 4a. supersede this order's prior ACTIVE runs only — legacy rows (status
    #     NULL) and other orders are never touched.
    old_ids = list(db.scalars(
        select(PrepRun.id).where(PrepRun.order_id == order_id,
                                 PrepRun.status == "active")).all())
    if old_ids:
        db.execute(delete(PrepOccupation).where(
            PrepOccupation.prep_run_id.in_(old_ids)))
        for r in db.scalars(select(PrepRun).where(PrepRun.id.in_(old_ids))).all():
            r.status = "superseded"

    # 4b. occupations held by OTHER orders' active runs
    occ_rows = db.execute(
        select(PrepOccupation.ingredient_id, func.sum(PrepOccupation.qty))
        .join(PrepRun, PrepRun.id == PrepOccupation.prep_run_id)
        .where(PrepRun.status == "active", PrepOccupation.order_id != order_id)
        .group_by(PrepOccupation.ingredient_id)
    ).all()
    occupied_other = {iid: float(qty) for iid, qty in occ_rows}

    result = build_result(order_lines, dish_lines, semi_lines, ingredients,
                          leaf_book, occupied_other)
    result["order"] = _order_info(order)

    run = PrepRun(order_id=order_id, created_at=datetime.utcnow(),
                  status="active", result_json=json.dumps(result, ensure_ascii=False))
    db.add(run)
    db.flush()
    for line in result["prep_lines"]:
        # FK to leaf_balances: a non-leaf id here is rejected by the database,
        # rolling back the entire generation (all three ledgers).
        db.add(PrepOccupation(prep_run_id=run.id, order_id=order_id,
                              ingredient_id=line["ingredient_id"],
                              qty=line["need_qty"]))

    # 5. one commit — book balances were never UPDATE/DELETE targets
    db.commit()
    db.refresh(run)
    return {"id": run.id, "order_id": order_id, "status": "active",
            "legacy": False, "created_at": run.created_at,
            "superseded_run_ids": old_ids, **result}
