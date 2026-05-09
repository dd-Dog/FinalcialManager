"""全库证券标的参考价同步（按 ``asset_type + symbol`` 去重后拉行情，写回 ``assets``）。"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.core.last_price_cn import fetch_last_price_cn
from backend.models.entities import Asset

logger = logging.getLogger(__name__)

# 两次拉取之间休眠，减轻对东财/天天基金的压力
_QUOTE_SLEEP_S = 0.12
_UPDATE_CHUNK = 500


def _norm_asset_key(asset_type: object, symbol: object) -> tuple[str, str]:
    at = (str(asset_type) if asset_type is not None else "").strip().lower()
    sym = (str(symbol) if symbol is not None else "").strip().upper()
    return (at, sym)


def run_sync_all_assets_ref_prices(db: Session) -> dict[str, int]:
    """
    扫描全部 ``assets`` 行，按 ``(asset_type, symbol)`` 去重后调用 ``fetch_last_price_cn``，
    将结果写回所有匹配行的 ``ref_last_price`` / ``ref_price_updated_at``。

    :return: 统计 ``{"unique_keys": n, "priced_keys": m, "rows_updated": r}``
    """
    rows = db.execute(select(Asset.id, Asset.asset_type, Asset.symbol)).all()
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for aid, at, sym in rows:
        groups[_norm_asset_key(at, sym)].append(int(aid))

    now = datetime.now(timezone.utc)
    priced = 0
    rows_updated = 0

    for key, ids in groups.items():
        at, sym = key
        try:
            price = fetch_last_price_cn(at, sym)
        except Exception:
            logger.exception("ref price fetch failed for %s %s", at, sym)
            time.sleep(_QUOTE_SLEEP_S)
            continue
        if price is None:
            time.sleep(_QUOTE_SLEEP_S)
            continue
        priced += 1
        fv = float(Decimal(str(price)))
        for i in range(0, len(ids), _UPDATE_CHUNK):
            chunk = ids[i : i + _UPDATE_CHUNK]
            res = db.execute(
                update(Asset)
                .where(Asset.id.in_(chunk))
                .values(ref_last_price=fv, ref_price_updated_at=now)
            )
            rows_updated += int(res.rowcount or 0)
        db.commit()

    return {"unique_keys": len(groups), "priced_keys": priced, "rows_updated": rows_updated}
