"""Import side-effect module: ensures every ORM model is registered on
Base.metadata before create_all() is called anywhere.
"""

from app.db.base_class import Base
from app.db.id_generator import IdCounter
from app.models import (
    BaselineStat,
    Edge,
    LineModel,
    MeasurementFieldMapping,
    MeasurementRecord,
    Monitor,
    Network,
    Node,
)

__all__ = [
    "Base",
    "IdCounter",
    "Network",
    "Node",
    "Edge",
    "LineModel",
    "Monitor",
    "BaselineStat",
    "MeasurementFieldMapping",
    "MeasurementRecord",
]
