"""Validated storage models for owner-scoped personal term cards."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from backend.schemas.enums import Role


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
ListText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
SourceInput = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class PersonalTermDraft(BaseModel):
    """A validated proposal payload; generation is implemented in a later stage."""

    model_config = ConfigDict(extra="forbid")

    role: Role
    label_ko: ShortText
    label_en: ShortText
    plain_meaning_ko: LongText
    reference_checkpoints_ko: list[ListText] = Field(default_factory=list, max_length=12)
    cautions_ko: list[ListText] = Field(default_factory=list, max_length=12)
    aliases_ko: list[ListText] = Field(default_factory=list, max_length=12)
    query_fragments_en: list[ListText] = Field(default_factory=list, max_length=12)
    source_input: SourceInput
    proposal_kind: Literal["descriptive", "coined", "ambiguous"]
    uncertainty_ko: LongText | None = None


class PersonalTermUpdate(BaseModel):
    """Editable proposal fields. Identity, ownership and source input stay immutable."""

    model_config = ConfigDict(extra="forbid")

    role: Role | None = None
    label_ko: ShortText | None = None
    label_en: ShortText | None = None
    plain_meaning_ko: LongText | None = None
    reference_checkpoints_ko: list[ListText] | None = None
    cautions_ko: list[ListText] | None = None
    aliases_ko: list[ListText] | None = None
    query_fragments_en: list[ListText] | None = None
    proposal_kind: Literal["descriptive", "coined", "ambiguous"] | None = None
    uncertainty_ko: LongText | None = None

    @model_validator(mode="after")
    def at_least_one_change(self):
        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")
        return self


class PersonalTermRecord(PersonalTermDraft):
    model_config = ConfigDict(extra="forbid")

    personal_term_id: UUID
    term_id: str = Field(pattern=r"^personal_[0-9a-f]{32}$")
    status: Literal["generating", "proposed", "active", "deleted", "failed"]
    layout_slot: int | None = Field(default=None, ge=0)
    generation_attempts: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class GeneratedPersonalTermDraft(BaseModel):
    """Strict LLM output; server-owned source_input is deliberately absent."""

    model_config = ConfigDict(extra="forbid")

    role: Role
    label_ko: ShortText
    label_en: ShortText
    plain_meaning_ko: LongText
    reference_checkpoints_ko: list[ListText] = Field(min_length=1, max_length=12)
    cautions_ko: list[ListText] = Field(default_factory=list, max_length=12)
    aliases_ko: list[ListText] = Field(default_factory=list, max_length=12)
    query_fragments_en: list[ListText] = Field(min_length=1, max_length=12)
    proposal_kind: Literal["descriptive", "coined", "ambiguous"]
    uncertainty_ko: LongText | None = None

    @model_validator(mode="after")
    def ambiguous_requires_uncertainty(self):
        if self.proposal_kind == "ambiguous" and self.uncertainty_ko is None:
            raise ValueError("ambiguous proposals require uncertainty_ko")
        return self

    def with_source_input(self, source_input: str) -> PersonalTermDraft:
        return PersonalTermDraft(**self.model_dump(), source_input=source_input)


class PersonalTermGenerationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personal_term_id: UUID
    term_id: str = Field(pattern=r"^personal_[0-9a-f]{32}$")
    status: Literal["generating", "proposed", "active", "deleted", "failed"]
    source_input: SourceInput
    generation_attempts: int = Field(ge=0)
    generation_error_code: str | None = None
    created_at: datetime
    updated_at: datetime
