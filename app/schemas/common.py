"""Shared schema building blocks."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, ClassVar, Generic, Self, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 320 or not _EMAIL.match(value):
        raise ValueError("not a valid email address")
    return value


#: Lower-cased, trimmed, basic-shape-checked email. (Deliverability is checked by Cognito.)
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

#: A day of the week, as a short lower-case code.
Weekday = Annotated[str, Field(pattern=r"^(mon|tue|wed|thu|fri|sat|sun)$")]
#: A local clock time "HH:MM" (24-hour).
ClockTime = Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]

_CURRENCY = re.compile(r"^[A-Z]{3}$")


def normalize_currency(value: str) -> str:
    value = value.strip().upper()
    if not _CURRENCY.match(value):
        raise ValueError("use a three-letter currency code, e.g. INR")
    return value


#: ISO 4217 three-letter currency code, stored upper-case ("inr" → "INR"). The database checks it too.
CurrencyCode = Annotated[str, Field(min_length=3, max_length=3), AfterValidator(normalize_currency)]


def not_in_the_future(year: int) -> int:
    # One day of slack: on 1 January in India it can still be 31 December in UTC.
    if year > (datetime.now(UTC) + timedelta(days=1)).year:
        raise ValueError("cannot be in the future")
    return year


#: A calendar year, from 1800 up to this year.
PastYear = Annotated[int, Field(ge=1800), AfterValidator(not_in_the_future)]


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


class UploadTicket(ApiModel):
    """Where to PUT one file (presigned S3 URL, size signed in). Send ``headers`` with the PUT."""

    key: str
    upload_url: str
    headers: dict[str, str]
    expires_in_seconds: int


class ViewLink(ApiModel):
    """A short-lived link to look at a private file. Every link handed out is audited."""

    url: str
    expires_in_seconds: int


class Page(ApiModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class PageParams(ApiModel):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
