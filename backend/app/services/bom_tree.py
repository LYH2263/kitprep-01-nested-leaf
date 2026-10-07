"""Tolerant nested BOM tree for display only.

Unlike the strict generation path (bom_engine), the tree never raises on a
cycle or an empty semi-finished node — it marks them so operators can see and
fix the problem. Generation remains the path that fails the whole run.
"""
from __future__ import annotations


def build_tree(dishes: list, ingredients: dict, lines: list) -> list[dict]:
    by_dish: dict[int, list] = {}
    by_semi: dict[int, list] = {}
    for l in lines:
        if l.dish_id is not None:
            by_dish.setdefault(l.dish_id, []).append(l)
        else:
            by_semi.setdefault(l.parent_ingredient_id, []).append(l)

    def node(line, seen: frozenset) -> dict:
        ing = ingredients[line.ingredient_id]
        n = {
            "ingredient_id": ing.id,
            "ingredient": ing.name,
            "code": ing.code,
            "qty": line.qty_per_portion,
            "unit": ing.unit,
            "kind": ing.kind,
        }
        if ing.kind == "semi":
            if ing.id in seen:
                n["cycle"] = True
                return n
            children = by_semi.get(ing.id, [])
            if not children:
                n["empty"] = True
                return n
            n["children"] = [node(c, seen | {ing.id}) for c in children]
        return n

    tree = []
    for d in dishes:
        tree.append({
            "dish": d.name,
            "code": d.code,
            "children": [node(l, frozenset()) for l in by_dish.get(d.id, [])],
        })
    return tree
