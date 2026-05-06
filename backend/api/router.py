from fastapi import APIRouter

from backend.api.routes import accounts, assets, auth, positions, reports, transactions, transfers

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
api_router.include_router(assets.router, prefix="/assets", tags=["assets"])
api_router.include_router(transactions.router, prefix="/transactions", tags=["transactions"])
api_router.include_router(transfers.router, prefix="/transfers", tags=["transfers"])
api_router.include_router(positions.router, prefix="/positions", tags=["positions"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
