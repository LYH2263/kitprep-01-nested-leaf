"""Pure engine tests — no database, always runnable."""
import pytest

from app.services.bom_engine import (
    BomCycleError, BomEmptySemiError, BomStructureError, build_result, explode_to_leaves,
)


def ing(iid, code, name="n", unit="kg", kind="leaf"):
    return {"code": code, "name": name, "unit": unit, "kind": kind}


def dish_line(d, i, q):
    return {"dish_id": d, "ingredient_id": i, "qty_per_portion": q}


def semi_line(p, i, q):
    return {"parent_ingredient_id": p, "ingredient_id": i, "qty_per_portion": q}


def test_multilevel_flatten_to_leaf():
    # dish 1 (40 portions) -> semi 100 (0.25) -> leaf 1 (0.25) = 2.5
    order_lines = [{"dish_id": 1, "portions": 40}]
    dish_lines = [dish_line(1, 100, 0.25)]
    semi_lines = [semi_line(100, 1, 0.25)]
    ingredients = {1: ing(1, "I-PR", "五花肉"), 100: ing(100, "I-LR", "卤肉", kind="semi")}
    need = explode_to_leaves(order_lines, dish_lines, semi_lines, ingredients)
    assert need == {1: pytest.approx(2.5)}
    assert 100 not in need  # semi never appears on the sheet


def test_shared_semi_merges_leaves():
    # two dishes share the same semi at different factors
    order_lines = [{"dish_id": 1, "portions": 10}, {"dish_id": 2, "portions": 20}]
    dish_lines = [dish_line(1, 100, 0.1), dish_line(2, 100, 0.2)]
    semi_lines = [semi_line(100, 1, 0.5)]
    ingredients = {1: ing(1, "I-PR"), 100: ing(100, "I-LR", kind="semi")}
    need = explode_to_leaves(order_lines, dish_lines, semi_lines, ingredients)
    # 10*0.1*0.5 + 20*0.2*0.5 = 0.5 + 2.0 = 2.5
    assert need == {1: pytest.approx(2.5)}


def test_cycle_raises_with_path():
    order_lines = [{"dish_id": 1, "portions": 1}]
    dish_lines = [dish_line(1, 100, 1.0)]
    semi_lines = [semi_line(100, 101, 1.0), semi_line(101, 100, 1.0)]
    ingredients = {100: ing(100, "A", kind="semi"), 101: ing(101, "B", kind="semi")}
    with pytest.raises(BomCycleError) as ei:
        explode_to_leaves(order_lines, dish_lines, semi_lines, ingredients)
    assert 100 in ei.value.path and 101 in ei.value.path


def test_self_cycle_raises():
    order_lines = [{"dish_id": 1, "portions": 1}]
    dish_lines = [dish_line(1, 100, 1.0)]
    semi_lines = [semi_line(100, 100, 1.0)]
    ingredients = {100: ing(100, "A", kind="semi")}
    with pytest.raises(BomCycleError):
        explode_to_leaves(order_lines, dish_lines, semi_lines, ingredients)


def test_empty_semi_raises():
    order_lines = [{"dish_id": 1, "portions": 1}]
    dish_lines = [dish_line(1, 100, 1.0)]
    ingredients = {1: ing(1, "I-PR"), 100: ing(100, "I-LR", kind="semi")}
    with pytest.raises(BomEmptySemiError) as ei:
        explode_to_leaves(order_lines, dish_lines, [], ingredients)
    assert ei.value.ingredient_id == 100


def test_leaf_with_children_raises():
    order_lines = [{"dish_id": 1, "portions": 1}]
    dish_lines = [dish_line(1, 1, 1.0)]
    semi_lines = [semi_line(1, 2, 1.0)]  # leaf 1 must not have children
    ingredients = {1: ing(1, "A", kind="leaf"), 2: ing(2, "B", kind="leaf")}
    with pytest.raises(BomStructureError):
        explode_to_leaves(order_lines, dish_lines, semi_lines, ingredients)


def test_dish_without_bom_and_unknown_child_raise():
    ingredients = {1: ing(1, "A")}
    with pytest.raises(BomStructureError):
        explode_to_leaves([{"dish_id": 9, "portions": 1}], [], [], ingredients)
    with pytest.raises(BomStructureError):
        explode_to_leaves([{"dish_id": 1, "portions": 1}], [dish_line(1, 77, 1)], [],
                          ingredients)
    with pytest.raises(BomStructureError):
        explode_to_leaves([], [], [], ingredients)


def test_shortage_uses_available_not_book():
    order_lines = [{"dish_id": 1, "portions": 10}]
    dish_lines = [dish_line(1, 1, 1.0)]
    ingredients = {1: ing(1, "A")}
    # book 8, another order already occupies 6 -> available 2, need 10 -> short 8
    res = build_result(order_lines, dish_lines, [], ingredients,
                       leaf_book={1: 8.0}, occupied_other={1: 6.0})
    line = res["prep_lines"][0]
    assert line["need_qty"] == 10
    assert line["book_qty"] == 8
    assert line["occupied_qty"] == 6
    assert line["available_qty"] == 2
    assert line["shortage"] == 8
    # overbooked: available goes negative, shortage tracks need - available
    res2 = build_result(order_lines, dish_lines, [], ingredients,
                        leaf_book={1: 3.0}, occupied_other={1: 5.0})
    l2 = res2["prep_lines"][0]
    assert l2["available_qty"] == -2
    assert l2["shortage"] == 12


def test_all_leaf_no_semi_backward_compatible():
    order_lines = [{"dish_id": 1, "portions": 10}, {"dish_id": 2, "portions": 5}]
    dish_lines = [dish_line(1, 1, 0.2), dish_line(2, 1, 0.3), dish_line(2, 2, 0.2)]
    ingredients = {1: ing(1, "A"), 2: ing(2, "B")}
    need = explode_to_leaves(order_lines, dish_lines, [], ingredients)
    assert need[1] == pytest.approx(3.5)
    assert need[2] == pytest.approx(1.0)
    res = build_result(order_lines, dish_lines, [], ingredients,
                       leaf_book={1: 1.0, 2: 10.0}, occupied_other={})
    assert res["prep_lines"][0]["shortage"] == pytest.approx(2.5)
    assert res["prep_lines"][1]["shortage"] == 0


def test_result_is_leaf_only_with_stats():
    order_lines = [{"dish_id": 1, "portions": 1}]
    dish_lines = [dish_line(1, 100, 1.0), dish_line(1, 2, 1.0)]
    semi_lines = [semi_line(100, 1, 1.0)]
    ingredients = {1: ing(1, "A"), 2: ing(2, "B"), 100: ing(100, "S", kind="semi")}
    res = build_result(order_lines, dish_lines, semi_lines, ingredients,
                       leaf_book={1: 0.0, 2: 5.0}, occupied_other={})
    ids = {l["ingredient_id"] for l in res["prep_lines"]}
    assert ids == {1, 2}
    assert 100 not in ids
    assert {s["ingredient_id"] for s in res["shortages"]} == {1}
    # shortages are the identical objects, not recomputed copies
    assert res["shortages"][0] is next(l for l in res["prep_lines"] if l["ingredient_id"] == 1)
    assert res["stats"]["ingredient_count"] == 2
    assert res["stats"]["shortage_count"] == 1
