import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import EmailStr
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import created_at_field

if TYPE_CHECKING:
    from app.models.item import Item


class UserRole(str, Enum):
    """Assignable roles; each maps onto the site-wide tier ladder
    (app/core/features.py). Stored as a plain varchar, so extending this
    enum is additive — no migration (column default stays `operator`)."""

    user = "user"
    admin = "admin"
    operator = "operator"
    maintenance = "maintenance"
    planner = "planner"
    customer = "customer"
    leadership = "leadership"
    developer = "developer"
    # Operator-tier access PLUS the beta audience (early-access features).
    beta_client = "beta_client"


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)
    role: UserRole = Field(default=UserRole.operator)
    # Customer-portal users are scoped to a single customer account.
    customer_id: uuid.UUID | None = Field(
        default=None, foreign_key="customer.id", nullable=True
    )


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(UserBase):
    email: EmailStr | None = Field(default=None, max_length=255)  # type: ignore[assignment]
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = created_at_field()
    items: list["Item"] = Relationship(back_populates="owner", cascade_delete=True)


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int
