import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.config import settings

_log = logging.getLogger(__name__)

engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)

# 在 import 后即补列，避免仅依赖 lifespan 且默认日志级别看不到 INFO 时「静默失败」。
try:
    from backend.db.schema_bootstrap import ensure_positions_opened_at_column

    ensure_positions_opened_at_column(engine)
except Exception:
    _log.exception("ensure_positions_opened_at_column failed during engine init")

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
