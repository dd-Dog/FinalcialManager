import json
import os
import time

import requests


def pack_response(response: requests.Response) -> dict:
    try:
        body = response.json()
    except Exception:
        body = response.text[:300]
    return {"status": response.status_code, "body": body}


def run_smoke(base: str, user_prefix: str, password: str) -> dict[str, dict]:
    username = f"{user_prefix}_{int(time.time())}"
    results: dict[str, dict] = {}
    results["meta"] = {"base_url": base, "username": username}

    response = requests.post(
        f"{base}/auth/register",
        json={"username": username, "password": password},
        timeout=10,
    )
    results["register"] = pack_response(response)

    response = requests.post(
        f"{base}/auth/login",
        json={"username": username, "password": password},
        timeout=10,
    )
    results["login"] = pack_response(response)
    if response.status_code != 200:
        print(json.dumps(results, ensure_ascii=False))
        raise SystemExit(1)

    token = response.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.post(
        f"{base}/accounts",
        headers=headers,
        json={"name": "bank", "account_type": "bank", "currency": "CNY", "initial_balance": "100000.00"},
        timeout=10,
    )
    results["create_account_bank"] = pack_response(response)
    bank_account_id = response.json()["data"]["id"]

    response = requests.post(
        f"{base}/accounts",
        headers=headers,
        json={"name": "alipay", "account_type": "alipay", "currency": "CNY", "initial_balance": "2000.00"},
        timeout=10,
    )
    results["create_account_alipay"] = pack_response(response)
    alipay_account_id = response.json()["data"]["id"]

    response = requests.post(
        f"{base}/accounts",
        headers=headers,
        json={"name": "disposable", "account_type": "cash", "currency": "CNY", "initial_balance": "0.00"},
        timeout=10,
    )
    results["create_account_disposable"] = pack_response(response)
    disposable_account_id = response.json()["data"]["id"]

    response = requests.delete(f"{base}/accounts/{disposable_account_id}", headers=headers, timeout=10)
    results["delete_account_empty"] = pack_response(response)

    response = requests.delete(f"{base}/accounts/{bank_account_id}", headers=headers, timeout=10)
    results["delete_account_with_activity"] = pack_response(response)

    response = requests.post(
        f"{base}/assets",
        headers=headers,
        json={"asset_type": "stock", "symbol": "600519", "name": "moutai", "market": "CN"},
        timeout=10,
    )
    results["create_asset"] = pack_response(response)
    asset_id = response.json()["data"]["id"]

    response = requests.post(
        f"{base}/transactions",
        headers=headers,
        json={
            "type": "income",
            "account_id": bank_account_id,
            "amount": "20000.00",
            "fee": "0",
            "category": "salary",
            "note": "income",
            "occurred_at": "2026-04-30T09:00:00+08:00",
        },
        timeout=10,
    )
    results["income"] = pack_response(response)

    response = requests.post(
        f"{base}/transactions",
        headers=headers,
        json={
            "type": "buy",
            "account_id": bank_account_id,
            "asset_id": asset_id,
            "amount": "10000.00",
            "quantity": "100",
            "price": "100.00",
            "fee": "5.00",
            "note": "buy",
            "occurred_at": "2026-04-30T10:00:00+08:00",
        },
        timeout=10,
    )
    results["buy"] = pack_response(response)

    response = requests.post(
        f"{base}/transactions",
        headers=headers,
        json={
            "type": "sell",
            "account_id": bank_account_id,
            "asset_id": asset_id,
            "amount": "3300.00",
            "quantity": "30",
            "price": "110.00",
            "fee": "3.00",
            "note": "sell",
            "occurred_at": "2026-04-30T11:00:00+08:00",
        },
        timeout=10,
    )
    results["sell"] = pack_response(response)

    response = requests.post(
        f"{base}/assets",
        headers=headers,
        json={"asset_type": "fund", "symbol": "ZZPATCH", "name": "patch del", "market": "CN"},
        timeout=10,
    )
    results["create_asset_patch_delete"] = pack_response(response)
    flat_asset_id = response.json()["data"]["id"]

    response = requests.patch(
        f"{base}/assets/{flat_asset_id}",
        headers=headers,
        json={"name": "patched name"},
        timeout=10,
    )
    results["patch_asset_no_position"] = pack_response(response)

    response = requests.delete(f"{base}/assets/{flat_asset_id}", headers=headers, timeout=10)
    results["delete_asset_no_tx"] = pack_response(response)

    response = requests.patch(
        f"{base}/assets/{asset_id}",
        headers=headers,
        json={"name": "nope"},
        timeout=10,
    )
    results["patch_asset_blocked_position"] = pack_response(response)

    response = requests.post(
        f"{base}/transfers",
        headers=headers,
        json={
            "from_account_id": bank_account_id,
            "to_account_id": alipay_account_id,
            "amount": "1000.00",
            "note": "transfer",
            "occurred_at": "2026-04-30T12:00:00+08:00",
        },
        timeout=10,
    )
    results["transfer"] = pack_response(response)

    response = requests.get(f"{base}/positions", headers=headers, timeout=10)
    results["positions"] = pack_response(response)

    response = requests.get(
        f"{base}/reports/pnl",
        headers=headers,
        params={"start_date": "2026-04-01T00:00:00+08:00", "end_date": "2026-04-30T23:59:59+08:00"},
        timeout=10,
    )
    results["pnl"] = pack_response(response)

    response = requests.get(f"{base}/accounts", headers=headers, timeout=10)
    results["accounts"] = pack_response(response)

    status_expect = {
        "patch_asset_blocked_position": 409,
        "delete_account_with_activity": 409,
    }
    checkpoints = {
        "all_steps_ok": all(
            step["status"] == status_expect.get(key, 200)
            for key, step in results.items()
            if key not in {"meta", "checkpoints"}
        ),
        "expected_position_qty": None,
        "expected_realized_pnl": None,
    }
    try:
        pos = results["positions"]["body"]["data"]["items"][0]
        checkpoints["expected_position_qty"] = pos.get("quantity") == "70.00"
        checkpoints["expected_realized_pnl"] = pos.get("realized_pnl") == "297.00"
    except Exception:
        checkpoints["expected_position_qty"] = False
        checkpoints["expected_realized_pnl"] = False
    results["checkpoints"] = checkpoints

    return results


def main() -> None:
    base = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api/v1")
    user_prefix = os.getenv("SMOKE_USER_PREFIX", "smoke")
    password = os.getenv("SMOKE_PASSWORD", "12345678")
    results = run_smoke(base=base, user_prefix=user_prefix, password=password)
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()
