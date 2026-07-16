from collections.abc import Generator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session

from app.core import security
from app.core.config import settings
from app.core.db import engine
from app.models import TokenPayload, User, UserRole

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)


def get_db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]
TokenDep = Annotated[str, Depends(reusable_oauth2)]


def get_current_user(session: SessionDep, token: TokenDep) -> User:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    user = session.get(User, token_data.sub)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_active_superuser(current_user: CurrentUser) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    return current_user


# ---- SmartForge RBAC (spec §11) ----
INTERNAL_ROLES = {
    UserRole.admin,
    UserRole.operator,
    UserRole.maintenance,
    UserRole.planner,
}


def get_current_internal_user(current_user: CurrentUser) -> User:
    """Allow only internal staff (not customer-portal accounts)."""
    if current_user.is_superuser:
        return current_user
    if current_user.role not in INTERNAL_ROLES:
        raise HTTPException(status_code=403, detail="Internal platform access required")
    return current_user


def get_current_customer_user(current_user: CurrentUser) -> User:
    """Allow only customer-portal accounts, which must be scoped to a customer."""
    if current_user.role != UserRole.customer or current_user.customer_id is None:
        raise HTTPException(status_code=403, detail="Customer portal access required")
    return current_user


InternalUser = Annotated[User, Depends(get_current_internal_user)]
CustomerUser = Annotated[User, Depends(get_current_customer_user)]
