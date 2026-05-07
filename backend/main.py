from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from backend.api.router import api_router


def create_app() -> FastAPI:
    app = FastAPI(title="Financial Manager API", version="0.1.0")
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/api/v1", include_in_schema=False)
    def api_v1_redirect_trailing_slash() -> RedirectResponse:
        """无尾斜杠的 /api/v1 重定向到 /api/v1/，避免浏览器直接打开时 404。"""
        return RedirectResponse(url="/api/v1/")

    return app


app = create_app()
