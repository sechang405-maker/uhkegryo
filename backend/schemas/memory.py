"""Structured, bounded conversation context and recall outputs."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.schemas.enums import Role

NO_RECORDS = "이 대화 기록에서 해당 내용을 확인할 수 없습니다."
TOO_MANY = "관련 기록이 많습니다. 어느 시기 또는 어떤 추천을 말씀하시나요?"


class MemoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContextUpdate(MemoryModel):
    role: Role
    term_id: str | None = None
    evidence: str = Field(min_length=1, max_length=500)


class RecallQuery(MemoryModel):
    mode: Literal["none", "recall", "mixed"]
    reference_action: Literal["update", "refresh_all", "refresh_roles"] = "update"
    refresh_roles: list[Role] = Field(default_factory=list, max_length=5)
    role: Role | None = None
    term_id: str | None = Field(default=None, max_length=200)
    keywords: list[str] = Field(default_factory=list, max_length=5)
    start: datetime | None = None
    end: datetime | None = None
    source_job_ids: list[UUID] = Field(default_factory=list, max_length=20)
    latest: bool = False

    @model_validator(mode="after")
    def bounds(self):
        if len(set(self.refresh_roles)) != len(self.refresh_roles):
            raise ValueError("duplicate refresh role")
        if self.reference_action != "refresh_roles" and self.refresh_roles:
            raise ValueError("refresh roles require refresh_roles action")
        if any(not word.strip() or len(word) > 100 for word in self.keywords):
            raise ValueError("invalid recall keyword")
        if any(value and value.utcoffset() is None for value in (self.start, self.end)):
            raise ValueError("recall dates require timezone")
        if self.start and self.end and self.start >= self.end:
            raise ValueError("invalid date range")
        return self


class Citation(MemoryModel):
    job_id: UUID
    quote: str = Field(min_length=1, max_length=500)


class RecallAnswer(MemoryModel):
    answer: str = Field(min_length=1, max_length=2000)
    citations: list[Citation] = Field(min_length=1, max_length=20)


class MemorySource(MemoryModel):
    job_id: UUID
    href: str

    @model_validator(mode="after")
    def local_link(self):
        if self.href != "/api/jobs/" + str(self.job_id):
            raise ValueError("source link must identify its job")
        return self
