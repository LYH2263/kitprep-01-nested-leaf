from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Ingredient, KitchenOrder, PrepRun
from app.services import prep_service
from app.services.bom_engine import BomCycleError, BomEmptySemiError, BomEngineError
router = APIRouter(prefix="/prep", tags=["prep"])


def _map_engine_error(db: Session, exc: BomEngineError) -> HTTPException:
    def code_of(iid: int) -> str | None:
        ing = db.get(Ingredient, iid)
        return ing.code if ing else None

    if isinstance(exc, BomCycleError):
        return HTTPException(400, detail={
            "code": "BOM_CYCLE",
            "message": "BOM 存在循环引用，生成失败",
            "path": [code_of(i) for i in exc.path],
        })
    if isinstance(exc, BomEmptySemiError):
        return HTTPException(400, detail={
            "code": "BOM_EMPTY_SEMI",
            "message": "半成品下层用料为空，生成失败",
            "ingredient_code": code_of(exc.ingredient_id),
        })
    return HTTPException(400, detail={"code": "BOM_STRUCTURE", "message": str(exc)})


@router.post("/run")
def run_prep(order_id: int = 1, db: Session = Depends(get_db)):
    try:
        return prep_service.generate_prep(db, order_id)
    except LookupError as e:
        db.rollback()
        raise HTTPException(404, str(e))
    except BomEngineError as e:
        db.rollback()
        raise _map_engine_error(db, e)
    except DBAPIError as e:
        db.rollback()
        pgcode = getattr(getattr(e, "orig", None), "pgcode", None)
        if pgcode in ("55P03", "40P01"):
            raise HTTPException(409, detail={"code": "GENERATION_BUSY",
                                             "message": "有另一张备料单正在生成，请重试"})
        raise


@router.get("/latest")
def latest(order_id: int = 1, db: Session = Depends(get_db)):
    order = db.get(KitchenOrder, order_id)
    if not order:
        raise HTTPException(404, "订单不存在")
    run = db.scalars(
        select(PrepRun).where(PrepRun.order_id == order_id)
        .order_by(PrepRun.id.desc())
    ).first()
    if not run:
        # GET must not write: return an empty sheet; only POST /run locks stock.
        return prep_service.empty_payload(order)
    return prep_service.run_payload(run)


@router.get("/shortages")
def shortages(order_id: int = 1, db: Session = Depends(get_db)):
    data = latest(order_id=order_id, db=db)
    return {"order_id": order_id, "run_id": data.get("id"),
            "status": data.get("status"), "legacy": data.get("legacy", False),
            "shortages": data.get("shortages", []),
            "stats": data.get("stats", {})}


@router.get("/history")
def history(order_id: int = 1, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(PrepRun).where(PrepRun.order_id == order_id)
        .order_by(PrepRun.id.desc())
    ).all()
    return [{"id": r.id, "status": r.status,
             "legacy": "version" not in (r.result_json or "{}"),
             "created_at": r.created_at} for r in rows]
