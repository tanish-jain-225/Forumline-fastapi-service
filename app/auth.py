from typing import AsyncGenerator
import uuid

from fastapi import Depends
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import AuthenticationBackend, BearerTransport, JWTStrategy
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

import os
from dotenv import load_dotenv
from app.db import User, get_async_session
from app.schemas import UserCreate, UserRead, UserUpdate

load_dotenv()

jwt_secret = os.getenv("JWT_SECRET")
if not jwt_secret:
    raise RuntimeError("JWT_SECRET is required")

jwt_lifetime_seconds = int(os.getenv("JWT_LIFETIME_SECONDS", "3600"))


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = jwt_secret
    verification_token_secret = jwt_secret


async def get_user_db(session: AsyncSession = Depends(get_async_session)) -> AsyncGenerator[SQLAlchemyUserDatabase, None]:
    yield SQLAlchemyUserDatabase(session, User)


async def get_user_manager(user_db: SQLAlchemyUserDatabase = Depends(get_user_db)) -> AsyncGenerator[UserManager, None]:
    yield UserManager(user_db)


from fastapi_users.authentication import CookieTransport

bearer_transport = BearerTransport(tokenUrl="auth/jwt/login")

def is_production() -> bool:
    env = os.getenv("APP_ENV", "development").lower()
    return env == "production" or os.getenv("RENDER", "").lower() == "true"


cookie_transport = CookieTransport(
    cookie_name="fastapiusersauth",
    cookie_max_age=jwt_lifetime_seconds,
    cookie_secure=is_production(),
)

def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(secret=jwt_secret, lifetime_seconds=jwt_lifetime_seconds)


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

cookie_backend = AuthenticationBackend(
    name="cookie",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [cookie_backend, auth_backend])

current_active_user = fastapi_users.current_user(active=True)

user_auth_router = fastapi_users.get_auth_router(auth_backend)
user_register_router = fastapi_users.get_register_router(UserRead, UserCreate)
user_users_router = fastapi_users.get_users_router(UserRead, UserUpdate)

