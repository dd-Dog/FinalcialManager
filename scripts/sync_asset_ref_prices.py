"""为全库 ``assets`` 同步参考市价（按类型+代码去重拉取，写 ``ref_last_price``）。

建议由 **cron / systemd timer / Windows 计划任务** 每日执行一次（如凌晨 2:00），与业务低峰一致。

在项目根目录::

    python scripts/sync_asset_ref_prices.py

依赖环境变量 ``DATABASE_URL``（或项目根 ``.env`` 由 pydantic-settings 加载）。
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("sync_asset_ref_prices")


def main() -> int:
    from backend.db.session import SessionLocal
    from backend.services.ref_price_sync import run_sync_all_assets_ref_prices

    db = SessionLocal()
    try:
        stats = run_sync_all_assets_ref_prices(db)
        logger.info("done: %s", json.dumps(stats, ensure_ascii=False))
    except Exception:
        logger.exception("sync failed")
        db.rollback()
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
