"""Concurrency tests against real PostgreSQL, using the after_locks seam to
make the lock interleaving deterministic. Auto-skipped without PostgreSQL."""
import threading
import time

import pytest
from sqlalchemy.exc import DBAPIError

from app.models.models import (
    Dish, Ingredient, KitchenOrder, LeafBalance, OrderLine, PrepOccupation, PrepRun,
    SemiBalance,
)
from app.services import prep_service
from app.services.inventory_service import adjust_book

pytestmark = pytest.mark.db


def _gen(SessionFactory, order_id, after_locks=None, errors=None):
    s = SessionFactory()
    try:
        return prep_service.generate_prep(s, order_id, after_locks=after_locks)
    except BaseException as e:  # recorded on the calling thread via join/result
        s.rollback()
        if errors is not None:
            errors.append(e)
        raise
    finally:
        s.close()


def _make_order2(db):
    d_jt = db.query(Dish).filter_by(code="D-JT").one()
    o2 = KitchenOrder(code="KO-0902", outlet="城西门店", status="open")
    db.add(o2); db.flush()
    db.add(OrderLine(order_id=o2.id, dish_id=d_jt.id, portions=10))
    db.commit()
    return o2.id


def test_same_order_barrage_single_active_set(client, db, SessionFactory, monkeypatch):
    monkeypatch.setattr(prep_service, "LOCK_TIMEOUT_MS", 30000)
    results, errors = [], []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        try:
            results.append(_gen(SessionFactory, 1))
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert errors == []
    assert len(results) == 8
    db.expire_all()
    active = db.query(PrepRun).filter_by(order_id=1, status="active").all()
    assert len(active) == 1
    need = {l["ingredient_id"]: l["need_qty"] for l in results[-1]["prep_lines"]}
    occ = {(o.prep_run_id, o.ingredient_id): round(o.qty, 3)
           for o in db.query(PrepOccupation).all()}
    assert occ == {(active[0].id, iid): round(q, 3) for iid, q in need.items()}
    # books never moved
    leaf = db.query(LeafBalance).count()
    assert leaf == 7
    assert db.query(SemiBalance).filter(
        SemiBalance.ingredient_id == db.query(Ingredient).filter_by(code="I-LR").one().id
    ).one().book_qty == 5.0


def test_semi_adjust_runs_during_generation_and_sheet_stays_leaf(
        client, db, SessionFactory, monkeypatch):
    monkeypatch.setattr(prep_service, "LOCK_TIMEOUT_MS", 30000)
    o2 = _make_order2(db)
    entered = threading.Event()
    release = threading.Event()

    def hold():
        entered.set()
        release.wait(timeout=30)

    t1_err = []

    def t1():
        try:
            _gen(SessionFactory, 1, after_locks=hold)
        except Exception as e:
            t1_err.append(e)

    th1 = threading.Thread(target=t1)
    th1.start()
    assert entered.wait(10)  # T1 now holds order-1 row + all leaf locks

    # T3: inbound to the SEMI book must succeed while T1 is still blocked
    s3 = SessionFactory()
    lu = s3.query(Ingredient).filter_by(code="I-LR").one()
    done = threading.Event()

    def t3():
        try:
            adjust_book(s3, lu.id, 10.0)
        finally:
            done.set(); s3.close()

    th3 = threading.Thread(target=t3)
    th3.start()
    assert done.wait(5), "半成品仓入库被生成阻塞，违反三套账独立"
    th3.join()

    # T2: cross-order generation must block on the shared leaf rows
    t2_box = {}

    def t2():
        try:
            t2_box["res"] = _gen(SessionFactory, o2)
        except Exception as e:
            t2_box["err"] = e

    th2 = threading.Thread(target=t2)
    th2.start()
    time.sleep(0.8)
    assert th2.is_alive(), "跨单生成应在叶料行锁上等待"

    release.set()
    th1.join(10); th2.join(10)
    assert t1_err == []
    assert "err" not in t2_box, t2_box.get("err")

    b2 = t2_box["res"]
    chicken = next(l for l in b2["prep_lines"] if l["ingredient_name"] == "鸡肉")
    # order1 active run occupies 6; order2 (10x0.12=1.2) must see it
    assert chicken["need_qty"] == pytest.approx(1.2)
    assert chicken["occupied_qty"] == pytest.approx(6)
    assert chicken["available_qty"] == pytest.approx(-1)
    assert chicken["shortage"] == pytest.approx(2.2)

    db.expire_all()
    assert db.query(PrepRun).filter_by(status="active").count() == 2
    # 7 leaves for order1 + 3 leaves for order2, every occupation on a leaf
    occ = db.query(PrepOccupation).all()
    leaf_ids = {i.id for i in db.query(Ingredient).filter_by(kind="leaf")}
    assert len(occ) == 10
    assert {o.ingredient_id for o in occ} <= leaf_ids
    # semi book gained exactly the inbound (5 -> 15); T1 changed nothing
    fresh = SessionFactory()
    assert fresh.query(SemiBalance).filter_by(ingredient_id=lu.id).one().book_qty == 15.0
    fresh.close()
    # leaf books unchanged from seed
    seed_book = {1: 8.0, 2: 3.0, 3: 5.0, 4: 20.0, 5: 4.0, 6: 2.0, 7: 1.5}
    assert {r.ingredient_id: r.book_qty for r in db.query(LeafBalance).all()} == seed_book


def test_cross_order_lock_ordering_no_deadlock(client, db, SessionFactory, monkeypatch):
    monkeypatch.setattr(prep_service, "LOCK_TIMEOUT_MS", 10000)
    o2 = _make_order2(db)

    def worker(order_id, errs):
        for _ in range(6):
            s = SessionFactory()
            try:
                prep_service.generate_prep(s, order_id)
            except DBAPIError as e:
                s.rollback()
                # lock_timeout contention is tolerable; a deadlock is not
                assert getattr(getattr(e, "orig", None), "pgcode", None) != "40P01"
                errs.append(e)
            finally:
                s.close()

    errs1, errs2 = [], []
    for _ in range(3):
        ta = threading.Thread(target=worker, args=(1, errs1))
        tb = threading.Thread(target=worker, args=(o2, errs2))
        ta.start(); tb.start(); ta.join(30); tb.join(30)
        assert not ta.is_alive() and not tb.is_alive()

    # settle both orders, then verify shared-leaf totals = need1 + need2
    _gen(SessionFactory, 1)
    _gen(SessionFactory, o2)
    db.expire_all()
    from sqlalchemy import func
    totals = {iid: round(q, 3) for iid, q in
              db.query(PrepOccupation.ingredient_id, func.sum(PrepOccupation.qty))
              .join(PrepRun, PrepRun.id == PrepOccupation.prep_run_id)
              .filter(PrepRun.status == "active")
              .group_by(PrepOccupation.ingredient_id).all()}
    # 鸡肉 6 + 1.2, 面条 10 + 2, 生抽 1.75 + 0.1
    assert totals[3] == pytest.approx(7.2)
    assert totals[5] == pytest.approx(12)
    assert totals[6] == pytest.approx(1.85)
