from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models.models import (
    BomLine, Dish, Ingredient, KitchenOrder, LeafBalance, OrderLine, SemiBalance,
)

def seed_if_empty(db: Session) -> None:
    if (db.scalar(select(func.count()).select_from(Dish)) or 0) > 0:
        return
    dishes = [("D-HS", "红烧肉套餐"), ("D-YC", "鱼香茄子"), ("D-JT", "鸡汤面")]
    dish_ids = {}
    for code, name in dishes:
        d = Dish(code=code, name=name, portion_unit="份")
        db.add(d); db.flush(); dish_ids[code] = d.id
    # (code, name, unit, kind, initial book in that kind's own warehouse)
    ings = [
        ("I-PR", "五花肉", "kg", "leaf", 8.0),
        ("I-EG", "茄子", "kg", "leaf", 3.0),
        ("I-CK", "鸡肉", "kg", "leaf", 5.0),
        ("I-RC", "大米", "kg", "leaf", 20.0),
        ("I-ND", "面条", "kg", "leaf", 4.0),
        ("I-SC", "生抽", "L", "leaf", 2.0),
        ("I-OL", "食用油", "L", "leaf", 1.5),
        ("I-LR", "卤肉", "kg", "semi", 5.0),
    ]
    ing_ids = {}
    for code, name, unit, kind, book in ings:
        i = Ingredient(code=code, name=name, unit=unit, kind=kind)
        db.add(i); db.flush(); ing_ids[code] = i.id
        if kind == "semi":
            db.add(SemiBalance(ingredient_id=i.id, book_qty=book))
        else:
            db.add(LeafBalance(ingredient_id=i.id, book_qty=book))
    bom = [
        # 红烧肉套餐 now hangs the semi-finished 卤肉 (0.25/份) instead of 五花肉;
        # 卤肉 itself consumes 五花肉 0.25 per kg.
        ("D-HS", "I-LR", 0.25), ("D-HS", "I-RC", 0.15), ("D-HS", "I-SC", 0.02), ("D-HS", "I-OL", 0.03),
        ("D-YC", "I-EG", 0.3), ("D-YC", "I-RC", 0.15), ("D-YC", "I-SC", 0.015), ("D-YC", "I-OL", 0.025),
        ("D-JT", "I-CK", 0.12), ("D-JT", "I-ND", 0.2), ("D-JT", "I-SC", 0.01),
        ("S:I-LR", "I-PR", 0.25),  # semi BOM edge
    ]
    for parent, icode, qty in bom:
        if parent.startswith("S:"):
            db.add(BomLine(parent_ingredient_id=ing_ids[parent[2:]],
                           ingredient_id=ing_ids[icode], qty_per_portion=qty))
        else:
            db.add(BomLine(dish_id=dish_ids[parent],
                           ingredient_id=ing_ids[icode], qty_per_portion=qty))
    order = KitchenOrder(code="KO-0901", outlet="城西门店", status="open")
    db.add(order); db.flush()
    for dcode, portions in [("D-HS", 40), ("D-YC", 30), ("D-JT", 50)]:
        db.add(OrderLine(order_id=order.id, dish_id=dish_ids[dcode], portions=portions))
    db.commit()
