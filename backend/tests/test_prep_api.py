"""DB-backed API tests. Auto-skipped when PostgreSQL is unreachable."""
import json

import pytest

from app.models.models import (
    BomLine, Ingredient, LeafBalance, PrepOccupation, PrepRun, SemiBalance,
)

pytestmark = pytest.mark.db


def _by_name(rows, name):
    return next(r for r in rows
               if r.get("name") == name or r.get("ingredient_name") == name)


def _books(db):
    leaf = {r.ingredient_id: r.book_qty for r in db.query(LeafBalance).all()}
    semi = {r.ingredient_id: r.book_qty for r in db.query(SemiBalance).all()}
    return leaf, semi


def test_seed_invariant_after_generate(client, db):
    res = client.post("/api/prep/run?order_id=1")
    assert res.status_code == 200, res.text
    body = res.json()
    names = {l["ingredient_name"] for l in body["prep_lines"]}
    assert "五花肉" in names
    assert "卤肉" not in names
    pork = _by_name(body["prep_lines"], "五花肉")
    assert pork["need_qty"] == pytest.approx(2.5)
    assert pork["book_qty"] == 8
    assert pork["occupied_qty"] == 0
    assert pork["available_qty"] == 8
    assert pork["shortage"] == 0

    shortages = {s["ingredient_name"]: s["shortage"] for s in body["shortages"]}
    assert shortages == {"茄子": 6, "鸡肉": 1, "面条": 6, "食用油": pytest.approx(0.45)}
    assert "生抽" not in shortages  # need 1.75 vs book 2 -> surplus
    assert body["stats"]["total_shortage_qty"] == pytest.approx(13.45)
    assert body["stats"]["total_need_qty"] == pytest.approx(41.7)

    # semi book untouched; leaf books untouched; 7 occupations on leaves only
    _, semi = _books(db)
    lu = db.query(Ingredient).filter_by(code="I-LR").one()
    assert semi[lu.id] == 5.0
    assert db.query(PrepOccupation).count() == 7
    for o in db.query(PrepOccupation).all():
        assert o.ingredient_id != lu.id
    inv = client.get("/api/inventory").json()
    assert {r["name"] for r in inv["semi"]} == {"卤肉"}
    assert _by_name(inv["semi"], "卤肉")["occupied_qty"] == 0
    assert _by_name(inv["leaf"], "五花肉")["occupied_qty"] == pytest.approx(2.5)
    assert _by_name(inv["leaf"], "五花肉")["available_qty"] == pytest.approx(5.5)


def test_books_never_change_through_generation(client, db):
    leaf0, semi0 = _books(db)
    for _ in range(3):
        r = client.post("/api/prep/run?order_id=1")
        assert r.status_code == 200
    leaf1, semi1 = _books(db)
    assert leaf1 == leaf0 and semi1 == semi0


def test_double_click_single_active_occupation_set(client, db):
    r1 = client.post("/api/prep/run?order_id=1")
    r2 = client.post("/api/prep/run?order_id=1")
    assert r1.status_code == r2.status_code == 200
    b1, b2 = r1.json(), r2.json()
    assert b2["superseded_run_ids"] == [b1["id"]]
    assert [(l["ingredient_id"], l["need_qty"], l["shortage"]) for l in b1["prep_lines"]] == \
           [(l["ingredient_id"], l["need_qty"], l["shortage"]) for l in b2["prep_lines"]]

    active = db.query(PrepRun).filter_by(status="active").all()
    assert len(active) == 1 and active[0].id == b2["id"]
    assert db.query(PrepRun).filter_by(status="superseded").count() == 1
    occ = db.query(PrepOccupation).all()
    assert len(occ) == 7
    assert {o.ingredient_id for o in occ} == {l["ingredient_id"] for l in b2["prep_lines"]}
    assert {round(o.qty, 3) for o in occ} == {l["need_qty"] for l in b2["prep_lines"]}

    hist = client.get("/api/prep/history?order_id=1").json()
    assert [h["status"] for h in hist] == ["active", "superseded"]


def test_cycle_full_rollback(client, db):
    # establish a good "latest sheet" first
    ok = client.post("/api/prep/run?order_id=1")
    assert ok.status_code == 200
    runs_before = db.query(PrepRun).count()
    occ_before = db.query(PrepOccupation).count()
    leaf0, semi0 = _books(db)
    latest_before = client.get("/api/prep/latest?order_id=1").json()["id"]

    # now introduce a cycle reachable from the order: 半A -> 半B -> 半A,
    # with 半A attached to 红烧肉套餐
    a = Ingredient(code="S-A", name="半A", unit="kg", kind="semi")
    b = Ingredient(code="S-B", name="半B", unit="kg", kind="semi")
    db.add_all([a, b]); db.flush()
    db.add_all([
        BomLine(parent_ingredient_id=a.id, ingredient_id=b.id, qty_per_portion=1.0),
        BomLine(parent_ingredient_id=b.id, ingredient_id=a.id, qty_per_portion=1.0),
    ])
    from app.models.models import Dish
    hs_dish = db.query(Dish).filter_by(code="D-HS").one()
    db.add(BomLine(dish_id=hs_dish.id, ingredient_id=a.id, qty_per_portion=1.0))
    db.commit()

    r = client.post("/api/prep/run?order_id=1")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "BOM_CYCLE"

    db.expire_all()
    assert db.query(PrepRun).count() == runs_before
    assert db.query(PrepOccupation).count() == occ_before
    assert _books(db) == (leaf0, semi0)
    assert client.get("/api/prep/latest?order_id=1").json()["id"] == latest_before
    sh = client.get("/api/prep/shortages?order_id=1").json()
    assert sh["run_id"] == latest_before


def test_empty_semi_full_rollback(client, db):
    # change 卤肉's child factor line away: delete its lower-level BOM
    lu = db.query(Ingredient).filter_by(code="I-LR").one()
    db.query(BomLine).filter_by(parent_ingredient_id=lu.id).delete()
    db.commit()
    runs_before = db.query(PrepRun).count()
    leaf0, semi0 = _books(db)
    r = client.post("/api/prep/run?order_id=1")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "BOM_EMPTY_SEMI"
    db.expire_all()
    assert db.query(PrepRun).count() == runs_before
    assert db.query(PrepOccupation).count() == 0
    assert _books(db) == (leaf0, semi0)
    assert client.get("/api/prep/shortages?order_id=1").json()["shortages"] == []


def test_legacy_run_never_muted(client, db):
    legacy_json = json.dumps({
        "prep_lines": [{"ingredient_id": 999, "ingredient_name": "卤肉", "stock_qty": 0}],
        "shortages": [], "stats": {},
    }, ensure_ascii=False)
    legacy = PrepRun(order_id=1, result_json=legacy_json, status=None)
    db.add(legacy); db.flush()
    # SQLAlchemy applies the Python-side default even for an explicit None,
    # so force the genuine pre-feature legacy state (NULL status) at the DB.
    from sqlalchemy import update
    db.execute(update(PrepRun).where(PrepRun.id == legacy.id).values(status=None))
    db.commit()
    db.refresh(legacy)
    legacy_id, legacy_blob = legacy.id, legacy.result_json

    r = client.post("/api/prep/run?order_id=1")
    assert r.status_code == 200
    db.expire_all()
    again = db.get(PrepRun, legacy_id)
    assert again.status is None
    assert again.result_json == legacy_blob

    latest = client.get("/api/prep/latest?order_id=1").json()
    assert latest["id"] == r.json()["id"] and latest["legacy"] is False
    hist = {h["id"]: h for h in client.get("/api/prep/history?order_id=1").json()}
    assert hist[legacy_id]["legacy"] is True


def test_get_endpoints_never_write(client, db):
    assert client.get("/api/prep/latest?order_id=1").json()["prep_lines"] == []
    assert client.get("/api/prep/shortages?order_id=1").json()["shortages"] == []
    assert db.query(PrepRun).count() == 0


def test_inbound_adjustment_only(client, db):
    pork = db.query(Ingredient).filter_by(code="I-PR").one()
    lu = db.query(Ingredient).filter_by(code="I-LR").one()
    r = client.post(f"/api/inventory/ingredients/{pork.id}/adjust", json={"delta": 2})
    assert r.status_code == 200 and r.json()["book_qty"] == pytest.approx(10)
    r = client.post(f"/api/inventory/ingredients/{lu.id}/adjust", json={"delta": 10})
    assert r.status_code == 200 and r.json()["book_qty"] == pytest.approx(15)
    assert client.post(f"/api/inventory/ingredients/{pork.id}/adjust", json={"delta": 0}).status_code == 422
    assert client.post(f"/api/inventory/ingredients/{pork.id}/adjust", json={"delta": -1}).status_code == 422
    assert client.post("/api/inventory/ingredients/999/adjust", json={"delta": 1}).status_code == 404

    # extra leaf inbound removes a shortage after regenerating; semi book stays
    egg = db.query(Ingredient).filter_by(code="I-EG").one()
    assert client.post(f"/api/inventory/ingredients/{egg.id}/adjust", json={"delta": 6}).status_code == 200
    body = client.post("/api/prep/run?order_id=1").json()
    assert "茄子" not in {s["ingredient_name"] for s in body["shortages"]}
    assert db.query(SemiBalance).filter_by(ingredient_id=lu.id).one().book_qty == pytest.approx(15)


def test_three_pages_share_one_occupation_set(client, db):
    body = client.post("/api/prep/run?order_id=1").json()
    inv = client.get("/api/inventory").json()
    prep = {l["ingredient_id"]: l["need_qty"] for l in body["prep_lines"]}
    stock = {r["ingredient_id"]: (r["book_qty"], r["occupied_qty"], r["available_qty"])
             for r in inv["leaf"]}
    rows = db.query(PrepOccupation.ingredient_id).all()
    occ_ids = {i for (i,) in rows}
    assert occ_ids == set(prep)
    for iid, need in prep.items():
        book, occ, avail = stock[iid]
        assert occ == pytest.approx(need)
        assert round(avail, 3) == round(book - occ, 3)
    # shortage page uses the same run's lines
    sh = client.get("/api/prep/shortages?order_id=1").json()
    assert sh["run_id"] == body["id"]
    assert {(s["ingredient_id"], s["shortage"]) for s in sh["shortages"]} == \
           {(l["ingredient_id"], l["shortage"]) for l in body["prep_lines"] if l["shortage"] > 0}
    assert all(r["occupied_qty"] == 0 for r in inv["semi"])


def test_cross_order_occupations_merge(client, db):
    from app.models.models import KitchenOrder, OrderLine, Dish
    d_jt = db.query(Dish).filter_by(code="D-JT").one()
    o2 = KitchenOrder(code="KO-0902", outlet="城西门店", status="open")
    db.add(o2); db.flush()
    db.add(OrderLine(order_id=o2.id, dish_id=d_jt.id, portions=10))
    db.commit()

    b1 = client.post("/api/prep/run?order_id=1").json()
    b2 = client.post(f"/api/prep/run?order_id={o2.id}").json()
    # 鸡肉: order1 need 6 + order2 need 1.2 = 7.2 occupied; order2 sees order1's 6
    chicken2 = _by_name(b2["prep_lines"], "鸡肉")
    assert chicken2["need_qty"] == pytest.approx(1.2)
    assert chicken2["occupied_qty"] == pytest.approx(6)
    assert chicken2["available_qty"] == pytest.approx(-1)
    assert chicken2["shortage"] == pytest.approx(2.2)
    assert db.query(PrepRun).filter_by(status="active").count() == 2

    # superseding order1 does not touch order2's occupations
    client.post("/api/prep/run?order_id=1")
    inv = client.get("/api/inventory").json()
    chicken_stock = _by_name(inv["leaf"], "鸡肉")
    assert chicken_stock["occupied_qty"] == pytest.approx(7.2)
