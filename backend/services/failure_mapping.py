"""Stable failure codes and fixed public messages; never serialize exception text."""
from typing import Literal

import asyncpg
import httpx

from backend.schemas import Failure
from backend.schemas.enums import FailureCode
from backend.services.catalog_repository import CatalogLoadError
from backend.services.llm import LLMError

FAILURE_MESSAGE = "현재 요청을 처리하지 못했습니다. 잠시 후 새 메시지로 다시 시도해 주세요."
DB_AUTH_ERRORS = (asyncpg.InvalidAuthorizationSpecificationError, asyncpg.InvalidCatalogNameError)
DB_SCHEMA_ERRORS = (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError, asyncpg.InvalidSchemaNameError)
DB_CONNECTION_ERRORS = (
    asyncpg.PostgresConnectionError, asyncpg.InterfaceError,
    asyncpg.CannotConnectNowError, asyncpg.TooManyConnectionsError,
)
DATABASE_ERRORS = DB_AUTH_ERRORS + DB_SCHEMA_ERRORS + DB_CONNECTION_ERRORS + (OSError, TimeoutError)


class OperationalFailure(RuntimeError):
    def __init__(self, code: FailureCode, message: str = "operation failed"):
        self.failure_code = FailureCode(code)
        super().__init__(message)


def classify_failure(
    error: Exception, *, context: Literal["database", "migration", "search"] | None = None
) -> FailureCode:
    if isinstance(error, (LLMError, OperationalFailure)):
        return error.failure_code
    if isinstance(error, CatalogLoadError):
        return FailureCode.CATALOG_INVALID_AT_STARTUP
    if isinstance(error, DB_AUTH_ERRORS):
        return FailureCode.CONFIGURATION_ERROR
    if isinstance(error, DB_SCHEMA_ERRORS):
        return FailureCode.DATABASE_MIGRATION_ERROR
    if isinstance(error, DB_CONNECTION_ERRORS):
        return FailureCode.DATABASE_UNAVAILABLE
    if context == "database" and isinstance(error, (OSError, TimeoutError)):
        return FailureCode.DATABASE_UNAVAILABLE
    if context == "migration" and isinstance(error, (ConnectionError, TimeoutError)):
        return FailureCode.DATABASE_UNAVAILABLE
    if context == "migration":
        return FailureCode.DATABASE_MIGRATION_ERROR
    if context == "search":
        if isinstance(error, ModuleNotFoundError):
            return FailureCode.CONFIGURATION_ERROR
        if isinstance(error, (TimeoutError, httpx.TimeoutException)):
            return FailureCode.SEARCH_TIMEOUT
        if isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 429:
            return FailureCode.SEARCH_RATE_LIMITED
        return FailureCode.SEARCH_UPSTREAM_UNAVAILABLE
    return FailureCode.INTERNAL_CODE_ERROR


def public_failure(error: Exception, **kwargs) -> Failure:
    return Failure(failure_code=classify_failure(error, **kwargs), user_message=FAILURE_MESSAGE)
