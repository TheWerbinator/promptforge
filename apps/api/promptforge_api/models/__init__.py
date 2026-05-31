"""SQLAlchemy ORM models.

All model classes inherit from `Base`. Importing this package side-effect registers
every model on `Base.metadata`, which Alembic uses for autogeneration.
"""

from promptforge_api.models.api_key import ApiKey
from promptforge_api.models.base import Base
from promptforge_api.models.job import Job
from promptforge_api.models.org import Membership, Org, OrgRole
from promptforge_api.models.prompt import Prompt, PromptVersion, PromptVisibility
from promptforge_api.models.refresh_token import RefreshToken
from promptforge_api.models.user import User

__all__ = [
    "ApiKey",
    "Base",
    "Job",
    "Membership",
    "Org",
    "OrgRole",
    "Prompt",
    "PromptVersion",
    "PromptVisibility",
    "RefreshToken",
    "User",
]
