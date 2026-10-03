from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Dashboard, User, utcnow
from ..schemas import DashboardPublic, Layout
from ..security import current_user
from ..resources import resource_path
from ..workspaces import get_personal_workspace
from ..sync.publisher import prepare_write, publish
from ..sync.adapters import get_adapter
from ..sync.adapters.personal_state import WIDGETS
from .personal_route import SafePersonalRoute

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], route_class=SafePersonalRoute)
DEFAULT_LAYOUT = Layout.model_validate_json(resource_path(
    "dashboard.json", Path(__file__).parents[3] / "src" / "data" / "dashboard.json"
).read_text(encoding="utf-8"))


def ensure_dashboard(db: Session, user: User, *, commit: bool = True) -> Dashboard:
    dashboard = db.scalar(select(Dashboard).where(Dashboard.user_id == user.id))
    if dashboard is None:
        dashboard = Dashboard(user_id=user.id, workspace_id=get_personal_workspace(db, user).id,
                              layout_json=DEFAULT_LAYOUT.model_dump(mode="json"))
        db.add(dashboard)
        db.flush()
        if commit:
            db.commit()
            db.refresh(dashboard)
        else:
            db.flush()
    return dashboard


@router.get("", response_model=DashboardPublic)
def get_dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = ensure_dashboard(db, user)
    # Public output follows the same catalog projection for mixed legacy blobs.
    adapter = get_adapter("dashboard.layout")
    data = adapter.schema.model_validate(adapter.serialize(item))
    layout = {"widgets": [dict(WIDGETS[widget.id].model_dump(mode="json"),
        position=widget.position.model_dump(), size=widget.size.model_dump()) for widget in data.widgets]}
    return DashboardPublic(id=item.id, user_id=item.user_id, name=item.name,
                           layout_json=layout, created_at=item.created_at, updated_at=item.updated_at)


@router.put("/layout", response_model=DashboardPublic)
def update_layout(payload: Layout, user: User = Depends(current_user), db: Session = Depends(get_db)):
    for widget in payload.widgets:
        if (widget.id not in WIDGETS or widget.type != WIDGETS[widget.id].type
                or widget.config or widget.datasource != WIDGETS[widget.id].datasource):
            raise HTTPException(422, "Unsupported widget configuration")
    prepare_write(db, user)
    dashboard = ensure_dashboard(db, user, commit=False)
    dashboard.layout_json = payload.model_dump(mode="json")
    dashboard.updated_at = utcnow()
    try:
        adapter = get_adapter("dashboard.layout")
        data = adapter.schema.model_validate(adapter.serialize(dashboard))
    except (ValidationError, ValueError):
        raise HTTPException(422, "Unsupported widget layout") from None
    adapter.apply_data(dashboard, data)
    publish(db, dashboard)
    db.commit()
    db.refresh(dashboard)
    return dashboard
