from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db.id_generator import next_id
from app.db.session import get_db
from app.models import BaselineStat, Edge, MeasurementFieldMapping, MeasurementRecord, Monitor, Network, Node
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


@router.get("", response_model=list[NetworkOut])
def list_networks(db: Session = Depends(get_db)) -> list[Network]:
    return db.query(Network).order_by(Network.created_at.desc()).all()


@router.get("/{network_id}", response_model=NetworkOut)
def get_network(network_id: str, db: Session = Depends(get_db)) -> Network:
    network = db.get(Network, network_id)
    if network is None:
        raise HTTPException(status_code=404, detail="Network not found")
    return network


@router.delete("/{network_id}", status_code=204)
def delete_network(network_id: str, db: Session = Depends(get_db)) -> None:
    network = db.get(Network, network_id)
    if network is None:
        raise HTTPException(status_code=404, detail="Network not found")

    # No ORM-level cascades are configured (see model comments), and LineModel
    # is a shared catalog that must survive network deletion -- everything
    # else scoped to this network is removed explicitly, children first.
    monitor_ids = [m.monitor_id for m in db.query(Monitor.monitor_id).filter(Monitor.network_id == network_id).all()]
    if monitor_ids:
        db.query(BaselineStat).filter(BaselineStat.monitor_id.in_(monitor_ids)).delete(synchronize_session=False)
    db.query(MeasurementRecord).filter(MeasurementRecord.network_id == network_id).delete(synchronize_session=False)
    db.query(MeasurementFieldMapping).filter(MeasurementFieldMapping.network_id == network_id).delete(
        synchronize_session=False
    )
    db.query(Monitor).filter(Monitor.network_id == network_id).delete(synchronize_session=False)
    db.query(Edge).filter(Edge.network_id == network_id).delete(synchronize_session=False)
    db.query(Node).filter(Node.network_id == network_id).delete(synchronize_session=False)
    db.delete(network)
    db.commit()


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
