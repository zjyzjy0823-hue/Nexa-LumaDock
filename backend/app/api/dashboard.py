from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Dashboard, User, utcnow
from ..schemas import DashboardPublic, Layout
from ..security import current_user

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
DEFAULT_LAYOUT = Layout.model_validate_json((Path(__file__).parents[3] / "src" / "data" / "dashboard.json").read_text(encoding="utf-8"))


def ensure_dashboard(db: Session, user: User) -> Dashboard:
    dashboard = db.scalar(select(Dashboard).where(Dashboard.user_id == user.id))
    if dashboard is None:
        dashboard = Dashboard(user_id=user.id, layout_json=DEFAULT_LAYOUT.model_dump(mode="json"))
        db.add(dashboard)
        db.commit()
        db.refresh(dashboard)
    return dashboard


@router.get("", response_model=DashboardPublic)
def get_dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return ensure_dashboard(db, user)


@router.put("/layout", response_model=DashboardPublic)
def update_layout(payload: Layout, user: User = Depends(current_user), db: Session = Depends(get_db)):
    dashboard = ensure_dashboard(db, user)
    dashboard.layout_json = payload.model_dump(mode="json")
    dashboard.updated_at = utcnow()
    db.commit()
    db.refresh(dashboard)
    return dashboard
