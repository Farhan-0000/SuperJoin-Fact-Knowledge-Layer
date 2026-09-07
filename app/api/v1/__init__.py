"""V1 API Router bundle."""

from fastapi import APIRouter

from app.api.v1.documents import router as documents_router
from app.api.v1.facts import router as facts_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.relationships import router as relationships_router
from app.api.v1.reprocess import router as reprocess_router

v1_router = APIRouter()

v1_router.include_router(documents_router)
v1_router.include_router(jobs_router)
v1_router.include_router(facts_router)
v1_router.include_router(relationships_router)
v1_router.include_router(knowledge_router)
v1_router.include_router(reprocess_router)

__all__ = ["v1_router"]
