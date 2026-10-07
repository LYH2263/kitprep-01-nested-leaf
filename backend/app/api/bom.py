from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import BomLine, Dish, Ingredient
from app.services.bom_tree import build_tree
router = APIRouter(prefix="/bom", tags=["bom"])

@router.get("")
def list_bom(db: Session = Depends(get_db)):
    dishes = {d.id: d for d in db.scalars(select(Dish)).all()}
    ings = {i.id: i for i in db.scalars(select(Ingredient)).all()}
    rows = db.scalars(select(BomLine).order_by(BomLine.dish_id, BomLine.id)).all()
    out = []
    for r in rows:
        child = ings[r.ingredient_id]
        parent_name = (dishes[r.dish_id].name if r.dish_id is not None
                       else ings[r.parent_ingredient_id].name)
        out.append({
            "id": r.id,
            "dish_id": r.dish_id,
            "parent_ingredient_id": r.parent_ingredient_id,
            "parent_name": parent_name,
            "ingredient_id": r.ingredient_id,
            "ingredient_name": child.name,
            "kind": child.kind,
            "qty_per_portion": r.qty_per_portion,
            "unit": child.unit,
        })
    return out

@router.get("/tree")
def bom_tree(db: Session = Depends(get_db)):
    dishes = db.scalars(select(Dish).order_by(Dish.id)).all()
    ings = {i.id: i for i in db.scalars(select(Ingredient)).all()}
    lines = db.scalars(select(BomLine).order_by(BomLine.id)).all()
    return build_tree(dishes, ings, lines)
