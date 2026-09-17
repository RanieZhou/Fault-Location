from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Monitor, Network
from app.schemas.monitor import MonitorCreate, MonitorOut, MonitorUpdate
from app.services.monitor_service import (
    MonitorError,
    MonitorNotFoundError,
    create_monitor,
    delete_monitor,
    list_monitors,
    update_monitor,
)

router = APIRouter(prefix="/api", tags=["monitors"])


def _get_network_or_404(network_id: str, db: Session) -> Network:
    network = db.get(Network, network_id)
    if network is None:
        raise HTTPException(status_code=404, detail="Network not found")
    return network


@router.get("/networks/{network_id}/monitors", response_model=list[MonitorOut])
def list_monitors_endpoint(network_id: str, db: Session = Depends(get_db)) -> list[Monitor]:
    network = _get_network_or_404(network_id, db)
    return list_monitors(db, network)


@router.post("/networks/{network_id}/monitors", response_model=MonitorOut)
def create_monitor_endpoint(network_id: str, payload: MonitorCreate, db: Session = Depends(get_db)) -> Monitor:
    network = _get_network_or_404(network_id, db)
    try:
        return create_monitor(db, network, payload.node_id, payload.canonical_name, payload.aliases)
    except MonitorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/monitors/{monitor_id}", response_model=MonitorOut)
def update_monitor_endpoint(monitor_id: str, payload: MonitorUpdate, db: Session = Depends(get_db)) -> Monitor:
    try:
        return update_monitor(db, monitor_id, payload)
    except MonitorNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MonitorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/monitors/{monitor_id}", status_code=204)
def delete_monitor_endpoint(monitor_id: str, db: Session = Depends(get_db)) -> None:
    try:
        delete_monitor(db, monitor_id)
    except MonitorNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
