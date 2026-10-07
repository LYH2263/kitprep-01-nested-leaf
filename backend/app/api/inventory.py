from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import AdjustIn
from app.services import inventory_service
router = APIRouter(prefix="/inventory", tags=["inventory"])

@router.get("")
def list_inventory(db: Session = Depends(get_db)):
    # Two physical books plus the live leaf occupation view.
    return inventory_service.list_ledgers(db)

@router.post("/ingredients/{ingredient_id}/adjust")
def adjust_inventory(ingredient_id: int, body: AdjustIn, db: Session = Depends(get_db)):
    try:
        return inventory_service.adjust_book(db, ingredient_id, body.delta)
    except LookupError as e:
        raise HTTPException(404, str(e))
