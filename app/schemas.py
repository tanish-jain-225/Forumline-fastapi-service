import uuid
from datetime import datetime

from fastapi_users import schemas
from pydantic import BaseModel, ConfigDict


class UserRead(schemas.BaseUser[uuid.UUID]):
    pass


class UserCreate(schemas.BaseUserCreate):
    pass


class UserUpdate(schemas.BaseUserUpdate):
    pass


class PostCreate(BaseModel):
    caption: str
    content: str


class PostUpdate(BaseModel):
    caption: str | None = None
    content: str | None = None


class PostRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    caption: str
    url: str
    content: str
    file_type: str | None
    file_name: str | None
    created_at: datetime


class CategoryCreate(BaseModel):
    name: str
    description: str | None = None


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime


class ThreadCreate(BaseModel):
    title: str
    body: str
    category_id: uuid.UUID


class ThreadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    body: str
    user_id: uuid.UUID
    category_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class CommentCreate(BaseModel):
    body: str


class CommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    body: str
    user_id: uuid.UUID
    thread_id: uuid.UUID
    created_at: datetime
    updated_at: datetime