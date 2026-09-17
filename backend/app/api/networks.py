from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db.id_generator import next_id
from app.db.session import get_db
from app.models import Network
from app.schemas.mapping import MappingImportResult
from app.schemas.network import NetworkCreate, NetworkOut
from app.services.mapping_import import MappingImportError, import_mapping

router = APIRouter(prefix="/api/networks", tags=["networks"])


@router.post("", response_model=NetworkOut)
def create_network(payload: NetworkCreate, db: Session = Depends(get_db)) -> Network:
    network = Network(
        network_id=next_id(db, "NET"),
        name=payload.name,
        voltage_kv=payload.voltage_kv,
        frequency_hz=payload.frequency_hz,
    )
    db.add(network)
    db.commit()
    db.refresh(network)
    return network


@router.get("/{network_id}", response_model=NetworkOut)
def get_network(network_id: str, db: Session = Depends(get_db)) -> Network:
    network = db.get(Network, network_id)
    if network is None:
        raise HTTPException(status_code=404, detail="Network not found")
    return network


@router.post("/{network_id}/mapping/import", response_model=MappingImportResult)
async def import_network_mapping(
    network_id: str,
    file: UploadFile = File(...),
    sheet_name: str = Form("Edges"),
    db: Session = Depends(get_db),
) -> MappingImportResult:
    network = db.get(Network, network_id)
    if network is None:
        raise HTTPException(status_code=404, detail="Network not found")

    file_bytes = await file.read()
    try:
        return import_mapping(db, network, file_bytes, sheet_name=sheet_name)
    except MappingImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
