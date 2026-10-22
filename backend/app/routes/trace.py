"""GET /trace/{user_id}: últimas herramientas usadas por el agente (panel lateral). [Pedro]"""
from fastapi import APIRouter

from .. import config

router = APIRouter()


@router.get("/trace/{user_id}")
def trace(user_id: str, limit: int = 20):
    if config.MOCK:
        return [{"tool": "search_memory", "args": {"initials": "m d l e"}, "result_summary": "4 memories", "ms": 85}]
    from ..db import postgres
    return postgres.recent_trace(user_id, limit)
