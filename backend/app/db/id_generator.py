from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db.base_class import Base


class IdCounter(Base):
    """Per-prefix monotonic counter used to mint human-scannable primary keys
    (e.g. N000067) without exposing raw autoincrement row ids as identifiers.
    """

    __tablename__ = "id_counters"

    entity_prefix: Mapped[str] = mapped_column(String, primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


def next_id(db: Session, prefix: str, width: int = 6) -> str:
    counter = db.get(IdCounter, prefix)
    if counter is None:
        counter = IdCounter(entity_prefix=prefix, last_value=0)
        db.add(counter)
    counter.last_value += 1
    db.flush()
    return f"{prefix}{counter.last_value:0{width}d}"
