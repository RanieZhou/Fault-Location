from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import LineModel
from app.schemas.line_model import LineModelCreate, LineModelOut, LineModelUpdate
from app.services.line_model_service import (
    LineModelInUseError,
    LineModelNotFoundError,
    create_line_model,
    delete_line_model,
    list_line_models,
    update_line_model,
)

router = APIRouter(prefix="/api/line-models", tags=["line-models"])


@router.get("", response_model=list[LineModelOut])
def list_line_models_endpoint(
    enabled_only: bool = Query(False),
    line_type: str | None = Query(None),
    db: Session = Depends(get_db),
) -> list[LineModel]:
    return list_line_models(db, enabled_only=enabled_only, line_type=line_type)


@router.post("", response_model=LineModelOut)
def create_line_model_endpoint(payload: LineModelCreate, db: Session = Depends(get_db)) -> LineModel:
    return create_line_model(db, payload)


@router.patch("/{line_model_id}", response_model=LineModelOut)
def update_line_model_endpoint(
    line_model_id: str, payload: LineModelUpdate, db: Session = Depends(get_db)
) -> LineModel:
    try:
        return update_line_model(db, line_model_id, payload)
    except LineModelNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{line_model_id}", status_code=204)
def delete_line_model_endpoint(line_model_id: str, db: Session = Depends(get_db)) -> None:
    try:
        delete_line_model(db, line_model_id)
    except LineModelNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LineModelInUseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
