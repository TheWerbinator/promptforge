"""Tenancy-scoped data access layer.

All org-scoped models go through `TenantRepository`. Routes never call
`session.execute` directly; they obtain a repository via the `get_repo`
dependency factory in `core/deps.py`.
"""

from promptforge_api.repositories.base import TenantRepository

__all__ = ["TenantRepository"]
