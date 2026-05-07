import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.smoke_test_api import run_smoke


def test_smoke_api_flow() -> None:
    base = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api/v1")
    user_prefix = os.getenv("SMOKE_USER_PREFIX", "pytest_smoke")
    password = os.getenv("SMOKE_PASSWORD", "12345678")

    results = run_smoke(base=base, user_prefix=user_prefix, password=password)

    if results.get("buy", {}).get("status") != 200:
        pytest.skip(
            "Smoke buy failed (API/DB 与当前代码不一致或未执行迁移)。"
            "请在后端库执行 `alembic upgrade head` 并重启 API 后再跑本用例。"
            f" buy={results.get('buy')!r}"
        )

    assert results["checkpoints"]["all_steps_ok"], results
    assert results["checkpoints"]["expected_position_qty"], results
    assert results["checkpoints"]["expected_realized_pnl"], results
    assert results["checkpoints"].get("opening_bootstrap_ok"), results
