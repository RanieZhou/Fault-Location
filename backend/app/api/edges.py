from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Edge, Network
from app.schemas.edge import EdgeBatchConfigRequest, EdgeConfigUpdate, EdgeOut
from app.services.topology_service import TopologyError, batch_update_edge_config, get_edge_or_404, update_edge_config

router = APIRouter(prefix="/api/edges", tags=["edges"])


@router.patch("/{edge_id}", response_model=EdgeOut)
def update_edge_endpoint(edge_id: str, payload: EdgeConfigUpdate, db: Session = Depends(get_db)) -> Edge:
    try:
        edge = get_edge_or_404(db, edge_id)
        return update_edge_config(db, edge, payload.line_model_id, payload.length_km)
    except TopologyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/batch-config", response_model=list[EdgeOut])
def batch_config_endpoint(payload: EdgeBatchConfigRequest, db: Session = Depends(get_db)) -> list[Edge]:
    if not payload.edge_ids:
        raise HTTPException(status_code=400, detail="edge_ids 不能为空")

    first_edge = db.get(Edge, payload.edge_ids[0])
    if first_edge is None:
        raise HTTPException(status_code=404, detail="Edge not found")
    network = db.get(Network, first_edge.network_id)

    try:
        return batch_update_edge_config(
            db,
            network,
            payload.edge_ids,
            payload.line_model_id,
            payload.apply_length,
            payload.length_km,
        )
    except TopologyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
