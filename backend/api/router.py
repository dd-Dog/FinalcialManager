from fastapi import APIRouter

from backend.api.routes import accounts, assets, auth, positions, reports, transactions, transfers

api_router = APIRouter()


@api_router.get("/", tags=["meta"])
def api_v1_root() -> dict[str, str]:
    """GET /api/v1/：无业务列表页时给浏览器一个可读的说明（非 HTML）。"""
    return {
        "service": "Financial Manager API",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "health": "/api/v1/health",
    }


@api_router.get("/health", tags=["health"])
def api_health() -> dict[str, str]:
    """部署自检：浏览器或 curl 访问 /api/v1/health 应返回 200。"""
    return {"status": "ok"}


api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
api_router.include_router(assets.router, prefix="/assets", tags=["assets"])
api_router.include_router(transactions.router, prefix="/transactions", tags=["transactions"])
api_router.include_router(transfers.router, prefix="/transfers", tags=["transfers"])
api_router.include_router(positions.router, prefix="/positions", tags=["positions"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
