from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.deps import DbSession, require
from app.models import User
from app.schemas import DashboardOut
from app.security.permissions import Permission
from app.services.dashboard import build_dashboard

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(
    db: DbSession, user: Annotated[User, Depends(require(Permission.VIEW_DATA))]
) -> dict[str, Any]:
    data = build_dashboard(db, user)
    db.commit()
    return data
