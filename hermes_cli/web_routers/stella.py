"""Stella Web API Router.

Exposes endpoints for:
1. Stella nested profile management (profiles/<id>/ with profile.json).
2. Hermes -> Stella one-click migration (detect, preview, execute, rollback).
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from stella.migration import HermesMigrationEngine
from stella.profiles import StellaProfileManager, sanitize_profile_id

router = APIRouter(prefix="/api/stella", tags=["stella"])


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------

class StellaProfileCreateRequest(BaseModel):
    display_name: str = Field(..., description="User-facing display name")
    profile_id: Optional[str] = Field(None, description="Optional custom ID")
    description: str = Field("", description="Profile description")
    avatar: str = Field("", description="Avatar icon or path")
    is_primary: bool = Field(False, description="Whether this is the primary profile")
    model: Optional[str] = None
    provider: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class StellaProfileUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    avatar: Optional[str] = None
    is_primary: Optional[bool] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    tags: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


class MigrationPreviewRequest(BaseModel):
    source_path: str
    target_profile_id: Optional[str] = "stella"


class MigrationExecuteRequest(BaseModel):
    source_path: str
    target_profile_id: Optional[str] = "stella"
    components: Optional[List[str]] = None
    overwrite: bool = False
    import_named_profiles: bool = False


class MigrationRollbackRequest(BaseModel):
    target_profile_id: str


# --------------------------------------------------------------------------
# Endpoints: Profiles
# --------------------------------------------------------------------------

@router.get("/profiles")
async def list_stella_profiles():
    """List all nested Stella profiles."""
    mgr = StellaProfileManager()
    mgr.ensure_root_layout(auto_create_default=True)
    profiles = mgr.list_profiles()
    return {"profiles": [p.to_dict() for p in profiles]}


@router.post("/profiles")
async def create_stella_profile(body: StellaProfileCreateRequest):
    """Create a new nested Stella profile under profiles/<id>/."""
    mgr = StellaProfileManager()
    try:
        profile = mgr.create_profile(
            display_name=body.display_name,
            profile_id=body.profile_id,
            description=body.description,
            avatar=body.avatar,
            is_primary=body.is_primary,
            model=body.model,
            provider=body.provider,
            tags=body.tags,
        )
        return {"success": True, "profile": profile.to_dict()}
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/profiles/{profile_id}")
async def get_stella_profile(profile_id: str):
    """Get metadata for a specific Stella profile."""
    mgr = StellaProfileManager()
    profile = mgr.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")
    return {"profile": profile.to_dict()}


@router.patch("/profiles/{profile_id}")
async def update_stella_profile(profile_id: str, body: StellaProfileUpdateRequest):
    """Update profile metadata (e.g. display name) without directory rename."""
    mgr = StellaProfileManager()
    try:
        updated = mgr.update_profile(
            profile_id=profile_id,
            display_name=body.display_name,
            description=body.description,
            avatar=body.avatar,
            is_primary=body.is_primary,
            model=body.model,
            provider=body.provider,
            tags=body.tags,
            metadata=body.metadata,
        )
        return {"success": True, "profile": updated.to_dict()}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/profiles/{profile_id}")
async def delete_stella_profile(profile_id: str, force: bool = False, archive: bool = True):
    """Safely delete or archive a Stella profile."""
    mgr = StellaProfileManager()
    try:
        deleted = mgr.delete_profile(profile_id, force=force, archive=archive)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")
        return {"success": True, "deleted_id": profile_id}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --------------------------------------------------------------------------
# Endpoints: Migration
# --------------------------------------------------------------------------

@router.get("/migration/detect")
async def detect_hermes_migration():
    """Detect existing Hermes installations on the host system."""
    engine = HermesMigrationEngine()
    detected = engine.detect_hermes_installations()
    return {"detected": [d.to_dict() for d in detected]}


@router.post("/migration/preview")
async def preview_hermes_migration(body: MigrationPreviewRequest):
    """Preview migratable components from a Hermes directory (dry run)."""
    engine = HermesMigrationEngine()
    try:
        preview = engine.preview_migration(
            source_path=body.source_path,
            target_profile_id=body.target_profile_id or "stella",
        )
        return {"success": True, "preview": preview.to_dict()}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/migration/execute")
async def execute_hermes_migration(body: MigrationExecuteRequest):
    """Perform one-click selective migration from Hermes to Stella."""
    engine = HermesMigrationEngine()
    try:
        manifest = engine.execute_migration(
            source_path=body.source_path,
            target_profile_id=body.target_profile_id or "stella",
            components=body.components,
            overwrite=body.overwrite,
            import_named_profiles=body.import_named_profiles,
        )
        return {"success": True, "manifest": manifest.to_dict()}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/migration/rollback")
async def rollback_hermes_migration(body: MigrationRollbackRequest):
    """Roll back a prior migration using the audit manifest."""
    engine = HermesMigrationEngine()
    pdir = engine.profile_mgr.get_profile_dir(body.target_profile_id)
    rolled_back = engine.rollback_migration(pdir)
    if not rolled_back:
        raise HTTPException(
            status_code=404,
            detail=f"No active migration manifest found to rollback in profile '{body.target_profile_id}'",
        )
    return {"success": True, "target_profile_id": body.target_profile_id}
