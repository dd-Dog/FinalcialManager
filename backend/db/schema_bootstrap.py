"""启动时补齐与 ORM 不一致的列，避免已有库缺列导致 500。"""

import logging
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def _positions_table_schema(engine: Engine) -> str | None:
    """PostgreSQL 固定查 ``public``，避免连接 ``search_path`` 不含 public 时误判表不存在。"""
    if engine.dialect.name in ("postgresql", "postgres"):
        return "public"
    return None


def ensure_positions_opened_at_column(engine: Engine) -> None:
    """若 ``positions`` 表存在且缺少 ``opened_at``，则执行 ``ADD COLUMN``（SQLite / PostgreSQL）。"""
    tbl_schema = _positions_table_schema(engine)
    try:
        insp = inspect(engine)
    except Exception:
        logger.exception("schema_bootstrap: inspect engine failed")
        return
    try:
        if not insp.has_table("positions", schema=tbl_schema):
            logger.warning(
                "schema_bootstrap: table positions not found (schema=%r), skip opened_at",
                tbl_schema,
            )
            return
    except Exception:
        logger.exception("schema_bootstrap: has_table(positions) failed")
        return

    try:
        col_names = {c["name"] for c in insp.get_columns("positions", schema=tbl_schema)}
    except Exception:
        logger.exception("schema_bootstrap: get_columns(positions) failed")
        return

    if "opened_at" in col_names:
        return

    dialect = engine.dialect.name
    if dialect == "sqlite":
        ddl = "ALTER TABLE positions ADD COLUMN opened_at TIMESTAMP"
    elif dialect in ("postgresql", "postgres"):
        ddl = "ALTER TABLE public.positions ADD COLUMN IF NOT EXISTS opened_at TIMESTAMPTZ"
    else:
        logger.warning(
            "schema_bootstrap: skip positions.opened_at (unsupported dialect %r)",
            dialect,
        )
        return

    try:
        with engine.begin() as conn:
            conn.execute(text(ddl))
    except Exception as e:
        if dialect == "sqlite" and "duplicate column name" in str(e).lower():
            logger.warning("schema_bootstrap: positions.opened_at already present (sqlite)")
        else:
            logger.exception(
                "schema_bootstrap: ADD COLUMN positions.opened_at failed "
                "(try: sudo -u postgres psql -d DB -c "
                "'ALTER TABLE public.positions ADD COLUMN IF NOT EXISTS opened_at TIMESTAMPTZ;')"
            )
            return

    try:
        insp2 = inspect(engine)
        col_after = {c["name"] for c in insp2.get_columns("positions", schema=tbl_schema)}
    except Exception:
        logger.exception("schema_bootstrap: re-inspect positions after ADD failed")
        return

    if "opened_at" not in col_after:
        logger.error(
            "schema_bootstrap: positions.opened_at still missing after ADD; "
            "run: alembic upgrade head OR ALTER TABLE public.positions ADD COLUMN opened_at TIMESTAMPTZ"
        )
    else:
        logger.warning("schema_bootstrap: positions.opened_at is now present (%s)", dialect)
