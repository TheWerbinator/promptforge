"""Aggregates all v1 routers."""

from fastapi import APIRouter

from promptforge_api.api.v1 import auth, demo, evals, prompts, runs, versions

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(demo.router)
api_router.include_router(prompts.router)
api_router.include_router(versions.router)
api_router.include_router(runs.versions_router)
api_router.include_router(runs.runs_router)
api_router.include_router(evals.suites_router)
api_router.include_router(evals.batches_router)
