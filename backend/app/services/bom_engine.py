"""Multi-level BOM explode.

Dish BOM lines may reference semi-finished ingredients (半成品), which have
their own BOM lines down to leaf raw materials (叶原料). Explosion multiplies
quantities along every path and merges by leaf ingredient. The result contains
leaf materials only — a semi can never appear on a prep sheet.

Pure functions over dicts/lists; no database access.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import asdict, dataclass

MAX_DEPTH = 100


class BomEngineError(Exception):
    """Base class: any failure aborts the whole generation (nothing written)."""


class BomCycleError(BomEngineError):
    def __init__(self, path: list[int]):
        self.path = path
        super().__init__(f"BOM 存在循环引用: {path}")


class BomEmptySemiError(BomEngineError):
    def __init__(self, ingredient_id: int):
        self.ingredient_id = ingredient_id
        super().__init__(f"半成品 {ingredient_id} 下层用料为空")


class BomStructureError(BomEngineError):
    pass


@dataclass
class NeedLine:
    ingredient_id: int
    ingredient_code: str
    ingredient_name: str
    unit: str
    kind: str
    need_qty: float
    book_qty: float        # 叶料仓账面 at generation
    occupied_qty: float    # other orders' active occupations at generation
    available_qty: float   # 可再用数量 = book - occupied
    shortage: float


def explode_to_leaves(
    order_lines: list[dict],
    dish_lines: list[dict],
    semi_lines: list[dict],
    ingredients: dict[int, dict],
) -> dict[int, float]:
    """Return {leaf_ingredient_id: total_qty}. Raises on cycle / empty semi /
    unknown child / leaf-with-children / dish without BOM."""
    by_dish: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for l in dish_lines:
        by_dish[l["dish_id"]].append((l["ingredient_id"], float(l["qty_per_portion"])))
    by_semi: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for l in semi_lines:
        by_semi[l["parent_ingredient_id"]].append(
            (l["ingredient_id"], float(l["qty_per_portion"])))

    need: dict[int, float] = {}

    def emit(iid: int, qty: float, stack: list[int], depth: int) -> None:
        if depth > MAX_DEPTH:
            raise BomStructureError(f"BOM 层级超过 {MAX_DEPTH}")
        ing = ingredients.get(iid)
        if ing is None:
            raise BomStructureError(f"BOM 引用了不存在的原料 {iid}")
        kind = ing.get("kind", "leaf")
        if kind == "leaf":
            if iid in by_semi:
                raise BomStructureError(f"叶原料 {iid} 不允许挂下层用料")
            need[iid] = need.get(iid, 0.0) + qty
            return
        if kind != "semi":
            raise BomStructureError(f"原料 {iid} 类型非法: {kind}")
        if iid in stack:
            raise BomCycleError(stack + [iid])
        children = by_semi.get(iid)
        if not children:
            raise BomEmptySemiError(iid)
        stack.append(iid)
        for cid, factor in children:
            emit(cid, qty * factor, stack, depth + 1)
        stack.pop()

    if not order_lines:
        raise BomStructureError("订单没有明细行")
    for ol in order_lines:
        children = by_dish.get(ol["dish_id"])
        if not children:
            raise BomStructureError(f"菜品 {ol['dish_id']} 没有出品定额(BOM)")
        for cid, factor in children:
            emit(cid, float(ol["portions"]) * factor, [], 0)

    # Fail-closed: the sheet is leaf-only by construction; never silently emit a semi.
    for iid in need:
        if ingredients[iid].get("kind", "leaf") != "leaf":
            raise BomStructureError(f"展平结果中出现非叶原料 {iid}")
    return need


def build_result(
    order_lines: list[dict],
    dish_lines: list[dict],
    semi_lines: list[dict],
    ingredients: dict[int, dict],
    leaf_book: dict[int, float],
    occupied_other: dict[int, float],
) -> dict:
    """Explode, then build prep lines with book/occupied/available/shortage.
    shortages are the same objects as the prep_lines subset."""
    need = explode_to_leaves(order_lines, dish_lines, semi_lines, ingredients)
    lines: list[NeedLine] = []
    for iid, qty in sorted(need.items()):
        ing = ingredients[iid]
        book = float(leaf_book.get(iid, 0.0))
        occupied = float(occupied_other.get(iid, 0.0))
        available = book - occupied
        lines.append(NeedLine(
            ingredient_id=iid,
            ingredient_code=ing["code"],
            ingredient_name=ing["name"],
            unit=ing.get("unit", ""),
            kind=ing.get("kind", "leaf"),
            need_qty=round(qty, 3),
            book_qty=round(book, 3),
            occupied_qty=round(occupied, 3),
            available_qty=round(available, 3),
            shortage=round(max(0.0, qty - available), 3),
        ))
    prep_lines = [asdict(l) for l in lines]
    shortages = [d for d in prep_lines if d["shortage"] > 0]
    return {
        "version": 2,
        "prep_lines": prep_lines,
        "shortages": shortages,
        "stats": {
            "ingredient_count": len(prep_lines),
            "shortage_count": len(shortages),
            "total_shortage_qty": round(sum(d["shortage"] for d in shortages), 3),
            "total_need_qty": round(sum(d["need_qty"] for d in prep_lines), 3),
        },
    }
