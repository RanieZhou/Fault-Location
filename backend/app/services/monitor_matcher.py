from sqlalchemy.orm import Session

from app.models import Monitor
from app.services.text_normalize import normalize_text


def match_monitor_name(db: Session, network_id: str, raw_name: str) -> str | None:
    """Raw name -> Normalize -> exact canonical match -> alias match -> None.

    Normalization is applied only to the comparison, never persisted onto the
    stored canonical_name/aliases -- the spec explicitly warns against
    silently rewriting names like "松平" -> "松坪"; only low-risk formatting
    noise (whitespace/fullwidth/case) is tolerated here.
    """
    normalized_raw = normalize_text(raw_name)
    monitors = db.query(Monitor).filter(Monitor.network_id == network_id, Monitor.enabled.is_(True)).all()

    for monitor in monitors:
        if normalize_text(monitor.canonical_name) == normalized_raw:
            return monitor.monitor_id

    for monitor in monitors:
        if any(normalize_text(alias) == normalized_raw for alias in monitor.aliases):
            return monitor.monitor_id

    return None
