from sqlalchemy.orm import Session

from app.db.id_generator import next_id
from app.models import Edge, LineModel
from app.schemas.line_model import LineModelCreate, LineModelUpdate


class LineModelError(ValueError):
    pass


class LineModelNotFoundError(LineModelError):
    pass


class LineModelInUseError(LineModelError):
    pass


def create_line_model(db: Session, payload: LineModelCreate) -> LineModel:
    line_model = LineModel(
        line_model_id=next_id(db, "LM"),
        line_type=payload.line_type,
        model_name=payload.model_name,
        r_ohm_per_km=payload.r_ohm_per_km,
        x_ohm_per_km=payload.x_ohm_per_km,
        c_nf_per_km=payload.c_nf_per_km,
        source="custom",
        enabled=True,
        remark=payload.remark,
    )
    db.add(line_model)
    db.commit()
    db.refresh(line_model)
    return line_model


def list_line_models(db: Session, enabled_only: bool = False, line_type: str | None = None) -> list[LineModel]:
    query = db.query(LineModel)
    if enabled_only:
        query = query.filter(LineModel.enabled.is_(True))
    if line_type:
        query = query.filter(LineModel.line_type == line_type)
    return query.order_by(LineModel.line_model_id).all()


def get_line_model_or_404(db: Session, line_model_id: str) -> LineModel:
    line_model = db.get(LineModel, line_model_id)
    if line_model is None:
        raise LineModelNotFoundError("Line model not found")
    return line_model


def update_line_model(db: Session, line_model_id: str, payload: LineModelUpdate) -> LineModel:
    line_model = get_line_model_or_404(db, line_model_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(line_model, field, value)
    db.commit()
    db.refresh(line_model)
    return line_model


def delete_line_model(db: Session, line_model_id: str) -> None:
    line_model = get_line_model_or_404(db, line_model_id)
    in_use = db.query(Edge).filter(Edge.line_model_id == line_model_id).count()
    if in_use > 0:
        raise LineModelInUseError("该型号已被 Edge 引用，无法删除，请先停用")
    db.delete(line_model)
    db.commit()
