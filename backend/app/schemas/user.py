"""Pydantic schemas for user APIs."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., min_length=3, max_length=255)


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = Field(default=None, min_length=3, max_length=255)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    email: str
    created_at: datetime
    updated_at: datetime
