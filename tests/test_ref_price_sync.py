"""``ref_price_sync``：按 (asset_type, symbol) 去重并写回 assets。"""
from __future__ import annotations

import time as time_module
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.db.base import Base
from backend.models.entities import Asset, User
from backend.services import ref_price_sync as m


@pytest.fixture
def mem_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine, future=True)
    db = S()
    db.add(User(username="u_a", password_hash="x", status=1))
    db.add(User(username="u_b", password_hash="x", status=1))
    db.commit()
    u1, u2 = db.scalars(select(User).order_by(User.id)).all()
    db.add(Asset(user_id=u1.id, asset_type="fund", symbol="260108", name="f1"))
    db.add(Asset(user_id=u2.id, asset_type="fund", symbol="260108", name="f2"))
    db.commit()
    yield db
    db.close()


def test_sync_one_fetch_updates_all_matching_rows(mem_db, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch(at: str, sym: str) -> Decimal | None:
        assert at == "fund" and sym == "260108"
        return Decimal("1.5")

    monkeypatch.setattr(m, "fetch_last_price_cn", fake_fetch)
    monkeypatch.setattr(time_module, "sleep", lambda *_: None)

    stats = m.run_sync_all_assets_ref_prices(mem_db)
    assert stats == {"unique_keys": 1, "priced_keys": 1, "rows_updated": 2}

    for ast in mem_db.scalars(select(Asset).order_by(Asset.id)).all():
        assert ast.ref_last_price is not None and float(ast.ref_last_price) == 1.5
        assert ast.ref_price_updated_at is not None


def test_sync_skip_when_fetch_returns_none(mem_db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m, "fetch_last_price_cn", lambda _at, _sym: None)
    monkeypatch.setattr(time_module, "sleep", lambda *_: None)
    stats = m.run_sync_all_assets_ref_prices(mem_db)
    assert stats["priced_keys"] == 0
    assert stats["rows_updated"] == 0
    for ast in mem_db.scalars(select(Asset)).all():
        assert ast.ref_last_price is None
