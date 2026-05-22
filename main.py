import os

from dotenv import load_dotenv
import uvicorn

if __name__ == "__main__":
    load_dotenv()

    env = os.getenv("APP_ENV", "development").lower()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = env != "production" and os.getenv("RELOAD", "").lower() != "false"

    uvicorn.run("app.app:app", host=host, port=port, reload=reload)
    # Run app by uvicorn server; use env-configured host/port and disable reload in production