"""Application entrypoint — run with `python -m app` or `uvicorn app.main:app`."""

from app.main import create_app
from app.config import get_settings


app = create_app()

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.app_host,
        port=settings.app_port,
        reload=True,
    )
