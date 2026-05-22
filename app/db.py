from collections.abc import AsyncGenerator
from datetime import datetime, timezone
import uuid

from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, relationship

from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from fastapi_users_db_sqlalchemy.generics import GUID

import os
from dotenv import load_dotenv

load_dotenv()


def get_utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase): # This is a base class for our SQLAlchemy models. It provides the necessary functionality for defining database tables and their relationships. By inheriting from this class, we can create our own models that represent the structure of our database tables.
    pass

class User(Base, SQLAlchemyBaseUserTableUUID):
    posts = relationship("Post", back_populates="user", cascade="all, delete-orphan")
    threads = relationship("Thread", back_populates="user", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="user", cascade="all, delete-orphan")


class Category(Base):
    __tablename__ = "categories"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=get_utc_now)

    threads = relationship("Thread", back_populates="category", cascade="all, delete-orphan")


class Thread(Base):
    __tablename__ = "threads"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=get_utc_now)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)

    user_id = Column(GUID, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    category_id = Column(GUID, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False)

    user = relationship("User", back_populates="threads")
    category = relationship("Category", back_populates="threads")
    comments = relationship("Comment", back_populates="thread", cascade="all, delete-orphan")


class Comment(Base):
    __tablename__ = "comments"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=get_utc_now)
    updated_at = Column(DateTime, default=get_utc_now, onupdate=get_utc_now)

    user_id = Column(GUID, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    thread_id = Column(GUID, ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)

    user = relationship("User", back_populates="comments")
    thread = relationship("Thread", back_populates="comments")

class Post(Base):
    __tablename__ = "posts"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)

    user_id = Column(GUID, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)

    caption = Column(String(255), nullable=False)
    url = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    file_type = Column(String(50), nullable=True)
    file_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=get_utc_now)

    user = relationship("User", back_populates="posts")

database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL is required")

engine = create_async_engine(database_url, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)

async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
