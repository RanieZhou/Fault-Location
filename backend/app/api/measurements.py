from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Network
from app.schemas.measurement import (
    FieldMappingOut,
    FieldMappingUpdate,
    MeasurementImportResult,
    ResolveUnmatchedRequest,
    ResolveUnmatchedResult,
    UnmatchedNameRow,
)
from app.services.measurement_adapter import (
    MeasurementImportError,
    get_field_mapping,
    import_measurements,
    list_unmatched_names,
    resolve_unmatched,
    set_field_mapping,
)

router = APIRouter(prefix="/api/networks", tags=["measurements"])


def _get_network_or_404(network_id: str, db: Session) -> Network:
    network = db.get(Network, network_id)
    if network is None:
        raise HTTPException(status_code=404, detail="Network not found")
    return network


@router.get("/{network_id}/measurements/mapping", response_model=FieldMappingOut)
def get_mapping_endpoint(network_id: str, db: Session = Depends(get_db)) -> FieldMappingOut:
    network = _get_network_or_404(network_id, db)
    return FieldMappingOut(network_id=network.network_id, mapping=get_field_mapping(db, network.network_id))


@router.post("/{network_id}/measurements/mapping", response_model=FieldMappingOut)
def set_mapping_endpoint(
    network_id: str, payload: FieldMappingUpdate, db: Session = Depends(get_db)
) -> FieldMappingOut:
    network = _get_network_or_404(network_id, db)
    try:
        mapping = set_field_mapping(db, network.network_id, payload.mapping)
    except MeasurementImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FieldMappingOut(network_id=network.network_id, mapping=mapping)


@router.post("/{network_id}/measurements/import", response_model=MeasurementImportResult)
async def import_measurements_endpoint(
    network_id: str,
    file: UploadFile = File(...),
    sheet_name: str | None = Form(None),
    db: Session = Depends(get_db),
) -> MeasurementImportResult:
    network = _get_network_or_404(network_id, db)
    file_bytes = await file.read()
    try:
        return import_measurements(db, network, file_bytes, sheet_name=sheet_name)
    except MeasurementImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{network_id}/measurements/unmatched", response_model=list[UnmatchedNameRow])
def list_unmatched_endpoint(network_id: str, db: Session = Depends(get_db)) -> list[UnmatchedNameRow]:
    network = _get_network_or_404(network_id, db)
    return list_unmatched_names(db, network.network_id)


@router.post("/{network_id}/measurements/resolve", response_model=ResolveUnmatchedResult)
def resolve_unmatched_endpoint(
    network_id: str, payload: ResolveUnmatchedRequest, db: Session = Depends(get_db)
) -> ResolveUnmatchedResult:
    network = _get_network_or_404(network_id, db)
    try:
        return resolve_unmatched(db, network, payload.monitor_name_raw, payload.monitor_id, payload.ignore)
    except MeasurementImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
