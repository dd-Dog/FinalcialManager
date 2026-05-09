import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from backend.api.router import api_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """可选：进程内每日 02:00 同步参考价（单 worker 时可用；多 worker 请用外部 cron 调 ``scripts/sync_asset_ref_prices.py``）。"""
    sched = None
    if os.getenv("FM_REF_PRICE_CRON", "").strip().lower() in ("1", "true", "yes", "on"):
        try:
            from zoneinfo import ZoneInfo

            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            logger.warning("FM_REF_PRICE_CRON set but APScheduler/zoneinfo unavailable; skip in-process cron")
        else:
            from backend.db.session import SessionLocal
            from backend.services.ref_price_sync import run_sync_all_assets_ref_prices

            def _job() -> None:
                db = SessionLocal()
                try:
                    stats = run_sync_all_assets_ref_prices(db)
                    logger.info("ref price cron: %s", stats)
                except Exception:
                    logger.exception("ref price cron failed")
                    db.rollback()
                finally:
                    db.close()

            tz_name = os.getenv("FM_REF_PRICE_TZ", "Asia/Shanghai")
            tz = ZoneInfo(tz_name)
            sched = BackgroundScheduler(timezone=tz)
            sched.add_job(
                _job,
                CronTrigger(hour=2, minute=0),
                id="sync_asset_ref_prices",
                replace_existing=True,
            )
            sched.start()
            logger.info("FM_REF_PRICE_CRON: daily 02:00 (%s)", tz_name)
    yield
    if sched is not None:
        sched.shutdown(wait=False)


def create_app() -> FastAPI:
    app = FastAPI(title="Financial Manager API", version="0.1.0", lifespan=lifespan)
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/api/v1", include_in_schema=False)
    def api_v1_redirect_trailing_slash() -> RedirectResponse:
        """无尾斜杠的 /api/v1 重定向到 /api/v1/，避免浏览器直接打开时 404。"""
        return RedirectResponse(url="/api/v1/")

    return app


app = create_app()
