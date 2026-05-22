import os
import pytest
from fastapi.testclient import TestClient
import uuid

# Set env variables before imports
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_test.db"
os.environ["IMAGEKIT_PRIVATE_KEY"] = "test-key"
os.environ["JWT_SECRET"] = "test-secret-long-enough-for-jwt-key-validation"

from app.app import app
from app.db import Category, Thread, User
from sqlalchemy import select

# Clean up test database before running tests
db_file = "./test_test.db"
if os.path.exists(db_file):
    try:
        os.remove(db_file)
    except Exception:
        pass


def test_complete_user_flow():
    # Use context manager to trigger lifespan and create tables
    with TestClient(app) as client:
        # 1. Register a new user
        reg_response = client.post(
            "/register",
            data={"email": "testuser@example.com", "password": "password123"},
            follow_redirects=False,
        )
        assert reg_response.status_code == 303
        assert "/login?registered=true" in reg_response.headers["location"]

        # 2. Try registering the same user again
        dup_response = client.post(
            "/register",
            data={"email": "testuser@example.com", "password": "password123"},
        )
        assert dup_response.status_code == 200
        assert "A user with this email already exists" in dup_response.text

        # 3. Try logging in with invalid credentials
        bad_login_response = client.post(
            "/login",
            data={"username": "testuser@example.com", "password": "wrongpassword"},
        )
        assert bad_login_response.status_code == 200
        assert "Invalid email or password" in bad_login_response.text

        # 4. Log in with valid credentials
        login_response = client.post(
            "/login",
            data={"username": "testuser@example.com", "password": "password123"},
            follow_redirects=False,
        )
        assert login_response.status_code == 303
        assert login_response.headers["location"] == "/"
        
        # Check if auth cookie is set
        assert "fastapiusersauth" in login_response.cookies
        auth_cookie = login_response.cookies["fastapiusersauth"]
        assert auth_cookie != ""

        # 5. Access /new (authenticated form) without cookie (should redirect to login if Accept has text/html)
        client.cookies.clear()
        unauth_response = client.get(
            "/new",
            headers={"Accept": "text/html"},
            follow_redirects=False,
        )
        assert unauth_response.status_code == 303
        assert unauth_response.headers["location"] == "/login"

        # 6. Access /new with cookie (should load the page successfully)
        client.cookies.set("fastapiusersauth", auth_cookie)
        auth_form_response = client.get("/new")
        assert auth_form_response.status_code == 200
        assert "Start a new thread" in auth_form_response.text

        # 7. Create a category
        cat_response = client.post(
            "/categories/new",
            data={"name": "Tech Discussion", "description": "All about tech"},
            follow_redirects=False,
        )
        assert cat_response.status_code == 303
        assert cat_response.headers["location"] == "/"

        # 8. Create a thread
        # First, find category ID in home page response
        home_response = client.get("/")
        assert home_response.status_code == 200
        assert "Tech Discussion" in home_response.text
        
        # Since we created it, we can check the database or extract it.
        # Let's extract the UUID from the category link in HTML
        # Category link is: /c/{uuid}
        import re
        cat_uuids = re.findall(r'/c/([0-9a-fA-F\-]{36})', home_response.text)
        assert len(cat_uuids) > 0
        cat_id = cat_uuids[0]

        # Submit thread
        thread_response = client.post(
            "/new",
            data={
                "title": "Welcome to Python 3.10",
                "body": "FastAPI is awesome!",
                "category_id": cat_id,
            },
            follow_redirects=False,
        )
        assert thread_response.status_code == 303
        assert "/t/" in thread_response.headers["location"]
        thread_id = thread_response.headers["location"].split("/t/")[1]

        # 9. View the thread and add a comment
        thread_view_response = client.get(f"/t/{thread_id}")
        assert thread_view_response.status_code == 200
        assert "Welcome to Python 3.10" in thread_view_response.text
        assert "FastAPI is awesome!" in thread_view_response.text

        # Post a comment with cookie
        comment_response = client.post(
            f"/t/{thread_id}/comment",
            data={"body": "Indeed it is!"},
            follow_redirects=False,
        )
        assert comment_response.status_code == 303
        assert comment_response.headers["location"] == f"/t/{thread_id}"

        # Verify comment is displayed on the thread page
        thread_view_updated = client.get(f"/t/{thread_id}")
        assert thread_view_updated.status_code == 200
        assert "Indeed it is!" in thread_view_updated.text

        # 9.5 Test Media Feed (Upload, Edit, Delete)
        # Upload a dummy file (image)
        import io
        dummy_file = io.BytesIO(b"dummy image data")
        upload_response = client.post(
            "/upload",
            files={"file": ("test.png", dummy_file, "image/png")},
            data={"caption": "Test Image Caption", "content": "This is a test image description"},
            headers={"Accept": "text/html"},
            follow_redirects=False,
        )
        # Since Accept is text/html, it should redirect to /posts
        assert upload_response.status_code == 303
        assert upload_response.headers["location"] == "/posts"

        # Verify the post is displayed on /posts
        feed_response = client.get("/posts")
        assert feed_response.status_code == 200
        assert "Test Image Caption" in feed_response.text
        assert "This is a test image description" in feed_response.text

        # Get the post's UUID from the feed API
        feed_api_response = client.get("/feed")
        assert feed_api_response.status_code == 200
        posts = feed_api_response.json()["posts"]
        assert len(posts) > 0
        
        # Find the post we just created
        test_post = [p for p in posts if p["caption"] == "Test Image Caption"][0]
        post_id = test_post["id"]

        # Edit the post caption and content
        edit_response = client.patch(
            f"/posts/{post_id}",
            data={"caption": "Updated Caption", "content": "Updated content"},
        )
        assert edit_response.status_code == 200
        assert edit_response.json()["detail"] == "Post updated successfully"

        # Verify edits are reflected
        feed_response_updated = client.get("/posts")
        assert feed_response_updated.status_code == 200
        assert "Updated Caption" in feed_response_updated.text
        assert "Updated content" in feed_response_updated.text
        assert "Test Image Caption" not in feed_response_updated.text

        # Delete the post
        delete_response = client.delete(
            f"/posts/{post_id}",
        )
        assert delete_response.status_code == 200
        assert delete_response.json()["detail"] == "Post deleted successfully"

        # Verify it is no longer in the feed
        feed_response_deleted = client.get("/posts")
        assert "Updated Caption" not in feed_response_deleted.text

        # 10. Logout and verify cookie is cleared
        logout_response = client.get(
            "/logout",
            follow_redirects=False,
        )
        assert logout_response.status_code == 303
        # In fastapi-users, clearing cookie sets max-age=0 or empty string
        # Let's check cookies
        cookie_val = logout_response.cookies.get("fastapiusersauth", "")
        assert cookie_val == ""

