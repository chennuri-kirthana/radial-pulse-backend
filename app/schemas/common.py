"""Shared schema building blocks."""

from __future__ import annotations

import re
from typing import Annotated, ClassVar, Generic, Self, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 320 or not _EMAIL.match(value):
        raise ValueError("not a valid email address")
    return value


#: Lower-cased, trimmed, basic-shape-checked email. (Deliverability is checked by Cognito/Google.)
Email = Annotated[str, AfterValidator(normalize_email)]

_COUNTRY = re.compile(r"^[A-Z]{2}$")


def normalize_country(value: str) -> str:
    value = value.strip().upper()
    if not _COUNTRY.match(value):
        raise ValueError("use a two-letter country code, e.g. IN")
    return value


#: ISO 3166 two-letter country code, stored upper-case ("in" → "IN"). The database checks it too.
#: The length rule is kept so the contract (openapi.json) still tells the screens "2 characters";
#: ApiModel strips spaces first, so " in " is accepted and becomes "IN".
CountryCode = Annotated[str, Field(min_length=2, max_length=2), AfterValidator(normalize_country)]

ShortText = Annotated[str, Field(min_length=1, max_length=200)]


class ApiModel(BaseModel):
    """Base for request/response models: reject unknown fields, read from ORM objects."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", str_strip_whitespace=True)


class PatchModel(ApiModel):
    """Base for PATCH bodies: a field may be LEFT OUT, but a required field cannot be set to null.

    List those fields in ``not_null_fields``. Without this, ``{"name": null}`` would reach a
    NOT NULL column and fail with a 500 instead of a clear 422.
    """

    not_null_fields: ClassVar[tuple[str, ...]] = ()

    @model_validator(mode="after")
    def _reject_nulls(self) -> Self:
        for name in self.not_null_fields:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class Page(ApiModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class PageParams(ApiModel):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
