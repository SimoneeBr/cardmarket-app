"""Runtime settings editable from the admin panel (defaults come from env)."""

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppSetting

_KEY = "runtime"


class RuntimeSettings(BaseModel):
    sync_enabled: bool = True
    sync_interval_seconds: int = Field(default=45, ge=10, le=3600)
    shop_name: str = Field(default="", max_length=80)


def _defaults() -> RuntimeSettings:
    return RuntimeSettings(sync_interval_seconds=get_settings().sync_interval_seconds)


def get_runtime_settings(db: Session) -> RuntimeSettings:
    row = db.get(AppSetting, _KEY)
    base = _defaults().model_dump()
    if row is not None:
        base.update(row.value)
    return RuntimeSettings.model_validate(base)


def update_runtime_settings(db: Session, changes: dict[str, Any]) -> RuntimeSettings:
    merged = get_runtime_settings(db).model_copy(update=changes)
    validated = RuntimeSettings.model_validate(merged.model_dump())
    row = db.get(AppSetting, _KEY)
    if row is None:
        db.add(AppSetting(key=_KEY, value=validated.model_dump()))
    else:
        row.value = validated.model_dump()
    return validated
