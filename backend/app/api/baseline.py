from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Network
from app.schemas.baseline import BaselineBuildResult, BaselineStatOut, NetworkReadiness
from app.services.baseline_service import build_baseline, get_baseline, get_network_readiness

router = APIRouter(prefix="/api/networks", tags=["baseline"])


def _get_network_or_404(network_id: str, db: Session) -> Network:
    network = db.get(Network, network_id)
    if network is None:
        raise HTTPException(status_code=404, detail="Network not found")
    return network


@router.post("/{network_id}/baseline/build", response_model=BaselineBuildResult)
def build_baseline_endpoint(network_id: str, db: Session = Depends(get_db)) -> BaselineBuildResult:
    network = _get_network_or_404(network_id, db)
    return build_baseline(db, network)


@router.get("/{network_id}/baseline", response_model=list[BaselineStatOut])
def get_baseline_endpoint(network_id: str, db: Session = Depends(get_db)) -> list[BaselineStatOut]:
    network = _get_network_or_404(network_id, db)
    return get_baseline(db, network)


@router.get("/{network_id}/readiness", response_model=NetworkReadiness)
def get_readiness_endpoint(network_id: str, db: Session = Depends(get_db)) -> NetworkReadiness:
    network = _get_network_or_404(network_id, db)
    return get_network_readiness(db, network)
