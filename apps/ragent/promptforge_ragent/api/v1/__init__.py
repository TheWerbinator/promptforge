"""v1 API router aggregation."""

from fastapi import APIRouter

from promptforge_ragent.api.v1 import chat

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(chat.router)
