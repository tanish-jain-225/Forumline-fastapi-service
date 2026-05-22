from fastapi import FastAPI, HTTPException, File, UploadFile, Form, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.db import create_db_and_tables, get_async_session, Post, User, Category, Thread, Comment
from app.schemas import (
    PostRead,
    CategoryCreate,
    CategoryRead,
    ThreadCreate,
    ThreadRead,
    CommentCreate,
    CommentRead,
)
from contextlib import asynccontextmanager
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from app.images import imageKit
from app.auth import (
    current_active_user,
    get_user_manager,
    user_auth_router,
    user_register_router,
    user_users_router,
    cookie_backend,
    fastapi_users,
)
from app.schemas import UserCreate
from fastapi_users.exceptions import UserAlreadyExists

import uuid
import shutil
import os
import tempfile
import subprocess
import sys

def run_migrations():
    try:
        # Run alembic upgrade head in a separate process to apply migrations
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            check=True
        )
        print("Migrations successfully applied:\n", result.stdout)
    except subprocess.CalledProcessError as e:
        print("Failed to run database migrations:\n", e.stderr)
        raise RuntimeError(f"Database migrations failed:\n{e.stderr}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    yield


async def populate_user_state(
    request: Request,
    user: User | None = Depends(fastapi_users.current_user(optional=True, active=True)),
):
    request.state.user = user


app = FastAPI(lifespan=lifespan, dependencies=[Depends(populate_user_state)])
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Error handler to redirect HTML clients to login page on 401 Unauthorized
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 401:
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return RedirectResponse(url="/login", status_code=303)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

cookie_auth_router = fastapi_users.get_auth_router(cookie_backend)

app.include_router(user_auth_router, prefix="/auth/jwt", tags=["auth"])
app.include_router(cookie_auth_router, prefix="/auth/cookie", tags=["auth"])
app.include_router(user_register_router, prefix="/auth", tags=["auth"])
app.include_router(user_users_router, prefix="/users", tags=["users"])


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


class Credentials:
    def __init__(self, username, password):
        self.username = username
        self.password = password


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, registered: bool = False):
    return templates.TemplateResponse(request, "login.html", {"registered": registered})


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    user_manager=Depends(get_user_manager),
):
    credentials = Credentials(username, password)
    user = await user_manager.authenticate(credentials)
    if user is None or not user.is_active:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid email or password", "username": username},
        )
    
    strategy = cookie_backend.get_strategy()
    token = await strategy.write_token(user)
    
    response = RedirectResponse(url="/", status_code=303)
    cookie_backend.transport._set_login_cookie(response, token)
    return response


@app.get("/logout")
async def logout(request: Request):
    response = RedirectResponse(url="/", status_code=303)
    cookie_backend.transport._set_logout_cookie(response)
    return response


@app.get("/register", response_class=HTMLResponse)
async def register_form(request: Request):
    return templates.TemplateResponse(request, "register.html", {})


@app.post("/register")
async def register_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    user_manager=Depends(get_user_manager),
):
    try:
        user = UserCreate(email=email, password=password)
        await user_manager.create(user, safe=True, request=request)
    except UserAlreadyExists:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": "A user with this email already exists", "email": email},
        )
    return RedirectResponse(url="/login?registered=true", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, session: AsyncSession = Depends(get_async_session)):
    categories = (await session.execute(select(Category).order_by(Category.name))).scalars().all()
    threads = (
        await session.execute(
            select(Thread)
            .options(selectinload(Thread.user), selectinload(Thread.category))
            .order_by(Thread.created_at.desc())
            .limit(10)
        )
    ).scalars().all()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "title": "Forumline",
            "subtitle": "A community feed for thoughtful conversations and quick updates.",
            "categories": categories,
            "threads": threads,
        },
    )


@app.get("/c/{category_id}", response_class=HTMLResponse)
async def category_view(
    request: Request,
    category_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    category_uuid = uuid.UUID(category_id)
    category = (await session.execute(select(Category).where(Category.id == category_uuid))).scalars().first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    threads = (
        await session.execute(
            select(Thread)
            .options(selectinload(Thread.user), selectinload(Thread.category))
            .where(Thread.category_id == category_uuid)
            .order_by(Thread.created_at.desc())
        )
    ).scalars().all()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "title": f"{category.name}",
            "subtitle": category.description or "Threads in this category.",
            "categories": [category],
            "threads": threads,
        },
    )


@app.get("/t/{thread_id}", response_class=HTMLResponse)
async def thread_view(
    request: Request,
    thread_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    thread_uuid = uuid.UUID(thread_id)
    thread = (
        await session.execute(
            select(Thread)
            .options(selectinload(Thread.user), selectinload(Thread.category))
            .where(Thread.id == thread_uuid)
        )
    ).scalars().first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    comments = (
        await session.execute(
            select(Comment)
            .options(selectinload(Comment.user))
            .where(Comment.thread_id == thread_uuid)
            .order_by(Comment.created_at.asc())
        )
    ).scalars().all()
    return templates.TemplateResponse(
        request,
        "thread.html",
        {"thread": thread, "comments": comments},
    )


@app.get("/new", response_class=HTMLResponse)
async def new_thread_form(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    categories = (await session.execute(select(Category).order_by(Category.name))).scalars().all()
    if not categories:
        category = Category(name="General", description="Community announcements and open chat.")
        session.add(category)
        await session.commit()
        await session.refresh(category)
        categories = [category]
    return templates.TemplateResponse(
        request,
        "new_thread.html",
        {"categories": categories},
    )


@app.post("/new")
async def new_thread_submit(
    title: str = Form(...),
    body: str = Form(...),
    category_id: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    category_uuid = uuid.UUID(category_id)
    category = (await session.execute(select(Category).where(Category.id == category_uuid))).scalars().first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    thread = Thread(
        title=title,
        body=body,
        user_id=user.id,
        category_id=category_uuid,
    )
    session.add(thread)
    await session.commit()
    return RedirectResponse(url=f"/t/{thread.id}", status_code=303)


@app.post("/t/{thread_id}/comment")
async def add_comment(
    thread_id: str,
    body: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    thread_uuid = uuid.UUID(thread_id)
    thread = (await session.execute(select(Thread).where(Thread.id == thread_uuid))).scalars().first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    comment = Comment(body=body, user_id=user.id, thread_id=thread_uuid)
    session.add(comment)
    await session.commit()
    return RedirectResponse(url=f"/t/{thread_id}", status_code=303)



@app.post("/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...), 
    caption: str = Form(""),
    content: str = Form(""),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    temp_file_path = None

    try:
        filename = file.filename or "upload.bin"
        suffix = os.path.splitext(filename)[1] or ".bin"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file_path = temp_file.name
            shutil.copyfileobj(file.file, temp_file)

        url = None
        file_name = None
        file_type = "video" if (file.content_type or "").startswith("video/") else "image"

        if imageKit is not None:
            try:
                # Try ImageKit upload
                with open(temp_file_path, "rb") as temp_stream:
                    upload_result = imageKit.files.upload(
                        file=temp_stream,
                        file_name=filename,
                        use_unique_file_name=True,
                        tags=["fastapi", "upload", "backend-uploads"],
                    )
                url = upload_result.url
                file_name = upload_result.name
            except Exception as upload_err:
                print(f"ImageKit upload failed, falling back to local storage: {upload_err}")
                # Ensure local uploads directory exists
                uploads_dir = os.path.join("static", "uploads")
                os.makedirs(uploads_dir, exist_ok=True)

                # Generate a unique local filename
                unique_filename = f"{uuid.uuid4()}{suffix}"
                local_path = os.path.join(uploads_dir, unique_filename)

                # Copy temp file to local storage
                shutil.copyfile(temp_file_path, local_path)

                # Set local URL relative to server root
                url = f"/static/uploads/{unique_filename}"
                file_name = unique_filename
        else:
            # ImageKit not configured; store locally
            uploads_dir = os.path.join("static", "uploads")
            os.makedirs(uploads_dir, exist_ok=True)

            unique_filename = f"{uuid.uuid4()}{suffix}"
            local_path = os.path.join(uploads_dir, unique_filename)

            shutil.copyfile(temp_file_path, local_path)

            url = f"/static/uploads/{unique_filename}"
            file_name = unique_filename

        post = Post(
            caption=caption,
            url=url,
            content=content,
            file_type=file_type,
            file_name=file_name,
            user_id=user.id,
        )

        session.add(post)
        await session.commit()
        await session.refresh(post)

        # For browser clients, redirect to the feed page
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return RedirectResponse(url="/posts", status_code=303)

        return {
            "id": post.id,
            "user_id": post.user_id,
            "caption": post.caption,
            "url": post.url,
            "content": post.content,
            "file_type": post.file_type,
            "file_name": post.file_name,
            "created_at": post.created_at,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        file.file.close()

@app.get("/feed", response_model=dict[str, list[PostRead]])
async def get_feed(session: AsyncSession = Depends(get_async_session)):
    result = await session.execute(select(Post).order_by(Post.created_at.desc()))
    posts = [row[0] for row in result.fetchall()]
    posts_data = []
    for post in posts:
        post_data = {
            "id": post.id,
            "user_id": post.user_id,
            "caption": post.caption,
            "url": post.url,
            "content": post.content,
            "file_type": post.file_type,
            "file_name": post.file_name,
            "created_at": post.created_at,
        }
        posts_data.append(post_data)

    return {"posts": posts_data}


@app.post("/categories", response_model=CategoryRead)
async def create_category(
    payload: CategoryCreate,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    category = Category(name=payload.name, description=payload.description)
    session.add(category)
    await session.commit()
    await session.refresh(category)
    return category


@app.get("/categories", response_model=list[CategoryRead])
async def list_categories(session: AsyncSession = Depends(get_async_session)):
    return (await session.execute(select(Category).order_by(Category.name))).scalars().all()


@app.post("/threads", response_model=ThreadRead)
async def create_thread(
    payload: ThreadCreate,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    category = (await session.execute(select(Category).where(Category.id == payload.category_id))).scalars().first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    thread = Thread(
        title=payload.title,
        body=payload.body,
        category_id=payload.category_id,
        user_id=user.id,
    )
    session.add(thread)
    await session.commit()
    await session.refresh(thread)
    return thread


@app.get("/threads", response_model=list[ThreadRead])
async def list_threads(session: AsyncSession = Depends(get_async_session)):
    return (
        await session.execute(select(Thread).order_by(Thread.created_at.desc()))
    ).scalars().all()


@app.get("/threads/{thread_id}", response_model=ThreadRead)
async def get_thread(thread_id: str, session: AsyncSession = Depends(get_async_session)):
    thread_uuid = uuid.UUID(thread_id)
    thread = (await session.execute(select(Thread).where(Thread.id == thread_uuid))).scalars().first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


@app.post("/threads/{thread_id}/comments", response_model=CommentRead)
async def create_comment(
    thread_id: str,
    payload: CommentCreate,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    thread_uuid = uuid.UUID(thread_id)
    thread = (await session.execute(select(Thread).where(Thread.id == thread_uuid))).scalars().first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    comment = Comment(body=payload.body, user_id=user.id, thread_id=thread_uuid)
    session.add(comment)
    await session.commit()
    await session.refresh(comment)
    return comment


@app.get("/threads/{thread_id}/comments", response_model=list[CommentRead])
async def list_comments(thread_id: str, session: AsyncSession = Depends(get_async_session)):
    thread_uuid = uuid.UUID(thread_id)
    return (
        await session.execute(
            select(Comment).where(Comment.thread_id == thread_uuid).order_by(Comment.created_at.asc())
        )
    ).scalars().all()

@app.delete("/posts/{post_id}")
async def delete_post(
    post_id: str,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    try:
        post_uuid = uuid.UUID(post_id)

        result = await session.execute(select(Post).where(Post.id == post_uuid))

        post = result.scalars().first() # Retrieve the first result from the query, which should be the post with the specified ID. If no post is found, this will return None.

        if not post:
            raise HTTPException(status_code=404, detail="Post not found")

        if post.user_id != user.id:
            raise HTTPException(status_code=403, detail="Not allowed to delete this post")
        
        await session.delete(post) # Mark the post for deletion in the database session. This prepares the post to be removed from the database when we commit the transaction. The post object is added to the session's list of pending deletions, and it will be deleted from the database when we call session.commit().
        await session.commit() # Commit the transaction to delete the post from the database. This is necessary to persist the changes made to the database session, such as deleting a post, so that it is removed from the database and can no longer be retrieved later.

        return {"detail": "Post deleted successfully"} # Return a success message indicating that the post was deleted successfully. This response will be sent back to the client to confirm that the deletion operation was completed without any issues.
    
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid post ID format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/posts/{post_id}") 
async def update_post(
    post_id: str,
    caption: str = Form(None),
    content: str = Form(None),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
): # updates only the caption and content of the post for now. We can extend this to allow updating other fields as well if needed.
    try:
        post_uuid = uuid.UUID(post_id)

        result = await session.execute(select(Post).where(Post.id == post_uuid))

        post = result.scalars().first()

        if not post:
            raise HTTPException(status_code=404, detail="Post not found")

        if post.user_id != user.id:
            raise HTTPException(status_code=403, detail="Not allowed to update this post")
        
        if caption is not None:
            post.caption = caption
        if content is not None:
            post.content = content

        await session.commit()
        await session.refresh(post)

        return {
            "detail": "Post updated successfully"
        }
    
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid post ID format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/posts", response_class=HTMLResponse)
async def feed_html(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
):
    result = await session.execute(
        select(Post)
        .options(selectinload(Post.user))
        .order_by(Post.created_at.desc())
    )
    posts = result.scalars().all()
    return templates.TemplateResponse(
        request,
        "feed.html",
        {"posts": posts}
    )


@app.get("/categories/new", response_class=HTMLResponse)
async def new_category_form(
    request: Request,
    user: User = Depends(current_active_user)
):
    return templates.TemplateResponse(request, "new_category.html", {})


@app.post("/categories/new")
async def create_category_submit(
    request: Request,
    name: str = Form(...),
    description: str = Form(None),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    # Check if category name already exists
    existing = (await session.execute(select(Category).where(Category.name == name))).scalars().first()
    if existing:
        return templates.TemplateResponse(
            request,
            "new_category.html",
            {
                "error": "A category with this name already exists",
                "name": name,
                "description": description,
            },
        )
    category = Category(name=name, description=description)
    session.add(category)
    await session.commit()
    return RedirectResponse(url="/", status_code=303)