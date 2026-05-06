# API 快速联调（5 分钟）

目标：按顺序跑通完整业务链路。

适用接口前缀：`http://127.0.0.1:8000/api/v1`

## 0) 启动服务

```bash
pip install -r requirements.txt
alembic upgrade head
uvicorn backend.main:app --reload
```

## 1) 注册账号

### curl
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"demo\",\"password\":\"12345678\"}"
```

### httpie
```bash
http POST "http://127.0.0.1:8000/api/v1/auth/register" username=demo password=12345678
```

## 2) 登录拿 token

### curl
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"demo\",\"password\":\"12345678\"}"
```

### httpie
```bash
http POST "http://127.0.0.1:8000/api/v1/auth/login" username=demo password=12345678
```

从响应中复制 `access_token`，下文记为 `TOKEN`。

## 3) 创建两个资金账户（后续用于交易和转账）

### 3.1 银行账户
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/accounts" \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"招商银行\",\"account_type\":\"bank\",\"currency\":\"CNY\",\"initial_balance\":\"100000.00\"}"
```

### 3.2 支付宝账户
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/accounts" \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"支付宝\",\"account_type\":\"alipay\",\"currency\":\"CNY\",\"initial_balance\":\"2000.00\"}"
```

记下返回的两个账户 ID：`BANK_ACCOUNT_ID`、`ALIPAY_ACCOUNT_ID`。

## 4) 创建资产标的

### 创建股票标的（示例：600519）
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/assets" \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"asset_type\":\"stock\",\"symbol\":\"600519\",\"name\":\"贵州茅台\",\"market\":\"CN\"}"
```

记下返回资产 ID：`ASSET_ID`。

## 5) 记一笔收入（入金）

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/transactions" \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"type\":\"income\",\"account_id\":BANK_ACCOUNT_ID,\"amount\":\"20000.00\",\"fee\":\"0\",\"category\":\"salary\",\"note\":\"4月工资\",\"occurred_at\":\"2026-04-30T09:00:00+08:00\"}"
```

## 6) 买入股票（更新现金 + 持仓）

> `amount = quantity * price`，示例：100 股 * 100 元 = 10000 元。

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/transactions" \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"type\":\"buy\",\"account_id\":BANK_ACCOUNT_ID,\"asset_id\":ASSET_ID,\"amount\":\"10000.00\",\"quantity\":\"100\",\"price\":\"100.00\",\"fee\":\"5.00\",\"note\":\"首次建仓\",\"occurred_at\":\"2026-04-30T10:00:00+08:00\"}"
```

## 7) 卖出部分仓位（更新现金 + 已实现收益）

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/transactions" \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"type\":\"sell\",\"account_id\":BANK_ACCOUNT_ID,\"asset_id\":ASSET_ID,\"amount\":\"3300.00\",\"quantity\":\"30\",\"price\":\"110.00\",\"fee\":\"3.00\",\"note\":\"部分止盈\",\"occurred_at\":\"2026-04-30T11:00:00+08:00\"}"
```

## 8) 账户转账（银行 -> 支付宝）

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/transfers" \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"from_account_id\":BANK_ACCOUNT_ID,\"to_account_id\":ALIPAY_ACCOUNT_ID,\"amount\":\"1000.00\",\"note\":\"日常备用金\",\"occurred_at\":\"2026-04-30T12:00:00+08:00\"}"
```

## 9) 查询结果（验证链路）

### 9.1 账户余额
```bash
curl -X GET "http://127.0.0.1:8000/api/v1/accounts" \
  -H "Authorization: Bearer TOKEN"
```

### 9.2 交易流水
```bash
curl -X GET "http://127.0.0.1:8000/api/v1/transactions?page=1&page_size=20" \
  -H "Authorization: Bearer TOKEN"
```

### 9.3 持仓
```bash
curl -X GET "http://127.0.0.1:8000/api/v1/positions" \
  -H "Authorization: Bearer TOKEN"
```

### 9.4 PnL 报表
```bash
curl -X GET "http://127.0.0.1:8000/api/v1/reports/pnl?start_date=2026-04-01T00:00:00%2B08:00&end_date=2026-04-30T23:59:59%2B08:00" \
  -H "Authorization: Bearer TOKEN"
```

## 10) 一次性检查点

当你看到以下结果，说明链路跑通：
- 能成功登录并拿到 `access_token`
- `accounts` 可看到两个账户且余额已变化
- `transactions` 有收入、买入、卖出、转账记录
- `positions` 有该股票持仓，且数量小于初始买入数量
- `reports/pnl` 返回 `income_total`、`expense_total`、`net_total`

---

如果你用 `httpie` 更顺手，可把上面每个 `curl` 按同路径替换成 `http` 命令，headers 和 json body 结构保持一致即可。

## 11) 自动化脚本（推荐）

项目内置了自动化联调脚本：
- `scripts/smoke_test_api.py`：执行完整链路并输出 JSON 结果
- `scripts/cleanup_smoke_users.py`：按用户名前缀清理测试数据

### 11.1 运行联调脚本

```bash
set DATABASE_URL=postgresql+psycopg://postgres:postgres123@localhost:5432/financial_manager
set API_BASE_URL=http://127.0.0.1:8000/api/v1
set SMOKE_USER_PREFIX=smoke
python scripts/smoke_test_api.py
```

关键输出字段：
- `meta.username`：本次生成的测试用户
- `checkpoints.all_steps_ok`：是否所有接口均 200
- `checkpoints.expected_position_qty`：持仓数量是否为 70
- `checkpoints.expected_realized_pnl`：已实现收益是否为 297.00

### 11.2 清理测试数据

```bash
set DATABASE_URL=postgresql://postgres:postgres123@localhost:5432/financial_manager
set SMOKE_USER_PREFIX=smoke
python scripts/cleanup_smoke_users.py
```

## 12) Pytest 回归方式

在 API 服务运行状态下执行：

```bash
set API_BASE_URL=http://127.0.0.1:8000/api/v1
set SMOKE_USER_PREFIX=pytest_smoke
pytest -q tests/test_smoke_api.py
```

通过后再执行一次清理：

```bash
set DATABASE_URL=postgresql://postgres:postgres123@localhost:5432/financial_manager
set SMOKE_USER_PREFIX=pytest_smoke
python scripts/cleanup_smoke_users.py
```
