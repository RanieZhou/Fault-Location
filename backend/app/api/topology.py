from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Network
from app.schemas.edge import EdgeTableRow
from app.schemas.network import NetworkOut
from app.schemas.topology import NetworkGraph, SourceSetRequest, TopologyValidationSummary
from app.services.topology_service import (
    TopologyError,
    get_graph,
    get_validation_summary,
    list_edges_table,
    set_source,
)

router = APIRouter(prefix="/api/networks", tags=["topology"])


def _get_network_or_404(network_id: str, db: Session) -> Network:
    network = db.get(Network, network_id)
    if network is None:
        raise HTTPException(status_code=404, detail="Network not found")
    return network


@router.post("/{network_id}/source", response_model=NetworkOut)
def set_network_source(network_id: str, payload: SourceSetRequest, db: Session = Depends(get_db)) -> Network:
    network = _get_network_or_404(network_id, db)
    try:
        return set_source(db, network, payload.node_id)
    except TopologyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{network_id}/graph", response_model=NetworkGraph)
def get_network_graph(network_id: str, db: Session = Depends(get_db)) -> NetworkGraph:
    network = _get_network_or_404(network_id, db)
    return get_graph(db, network)


@router.get("/{network_id}/validation", response_model=TopologyValidationSummary)
def get_network_validation(network_id: str, db: Session = Depends(get_db)) -> TopologyValidationSummary:
    network = _get_network_or_404(network_id, db)
    return get_validation_summary(db, network)


@router.get("/{network_id}/edges", response_model=list[EdgeTableRow])
def get_network_edges_table(network_id: str, db: Session = Depends(get_db)) -> list[EdgeTableRow]:
    network = _get_network_or_404(network_id, db)
    return list_edges_table(db, network)
