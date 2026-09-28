from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Client
from ..security import client_from_token
from ..sync.service import apply_mutation, get_changes


router = APIRouter(prefix="/api/v1/sync", tags=["sync"])


class MutationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocolVersion: int = Field(default=1, ge=1, le=1)
    mutations: list[dict] = Field(min_length=1, max_length=100)


@router.post("/mutations")
def mutations(payload: MutationBatch, client: Client = Depends(client_from_token),
              db: Session = Depends(get_db)):
    return {"protocolVersion": 1,
            "results": [apply_mutation(db, client, mutation) for mutation in payload.mutations]}


@router.get("/changes")
def changes(cursor: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=100),
            client: Client = Depends(client_from_token), db: Session = Depends(get_db)):
    return get_changes(db, client.workspace_id, cursor, limit)
