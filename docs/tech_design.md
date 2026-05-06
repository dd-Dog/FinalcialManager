# FinancialManager 技术设计文档

本文档用于指导“功能三：理财管理”模块的实现，覆盖模块职责、接口草案和数据库表结构 SQL。

## 1. 设计目标与边界

### 1.1 目标
- 管理存款、基金、股票等投资类资产。
- 支持可追溯的交易流水和账户转账。
- 支持持仓与收益统计，并通过 Web 面板操作。
- 提供 AI 辅助分析能力（可配置模型提供方）。

### 1.2 边界
- 当前版本不覆盖日常消费流水。
- 账务、余额、收益计算由后端业务逻辑实现，不依赖大模型计算。
- AI 模块只做分析与建议，不直接写入账务数据。

### 1.3 非功能要求
- 一致性：转账和交易入账必须使用事务，确保原子性。
- 可追溯：任何影响余额/持仓的动作都要保留历史记录。
- 可扩展：模型供应商、资产类型、交易类型可配置扩展。

## 2. 模块职责

建议目录结构：

```text
backend/
  api/
  services/
  repositories/
  models/
  schemas/
  auth/
core/
frontend/
docs/
```

### 2.1 backend/api
- 职责：提供 REST API，进行参数校验、鉴权、返回统一响应格式。
- 不负责：复杂业务计算（下沉到 services）。

### 2.2 backend/services
- 职责：核心业务编排与规则校验。
- 示例：
  - `account_service`：账户管理、余额校验。
  - `transaction_service`：收入/支出/买卖/转账入账。
  - `position_service`：持仓成本与数量变更。
  - `report_service`：收益与资产分布统计。
  - `ai_advisor_service`：拼装上下文并调用 LLM provider。

### 2.3 backend/repositories
- 职责：数据库 CRUD，屏蔽 SQL 细节。
- 约束：不承载跨实体业务规则。

### 2.4 backend/models + schemas
- `models`：ORM 模型或数据库实体定义。
- `schemas`：请求/响应 DTO（例如 Pydantic 模型）。

### 2.5 backend/auth
- 职责：账号密码认证（MVP），token 发放与鉴权。
- 后续扩展：rsa.pub 认证方式。

### 2.6 core
- 职责：纯业务计算逻辑（收益计算、平均成本、分布统计等），可单元测试。

### 2.7 frontend
- 职责：资产总览、交易录入、历史查询、收益看板、AI 建议展示。

## 3. 系统流程（关键路径）

### 3.1 转账流程
1. 校验来源账户余额是否充足。
2. 开启数据库事务。
3. 写入一条 `transactions`（`type=transfer`）。
4. 写入 `transfer_records`（from_account -> to_account）。
5. 更新两个账户余额。
6. 提交事务。

### 3.2 基金/股票买卖流程
1. 校验账户余额（买入）或持仓数量（卖出）。
2. 写入 `transactions`（buy/sell）。
3. 更新 `positions` 持仓数量、成本、已实现收益。
4. 更新关联资金账户余额。
5. 提交事务。

## 4. 接口草案（REST）

统一前缀：`/api/v1`
统一响应：
- 成功：`{"code":0,"message":"ok","data":{...}}`
- 失败：`{"code":<non-zero>,"message":"error detail"}`

### 4.1 认证

#### POST `/auth/register`
- 请求体：
```json
{
  "username": "demo",
  "password": "******"
}
```
- 返回：用户基础信息。

#### POST `/auth/login`
- 请求体：
```json
{
  "username": "demo",
  "password": "******"
}
```
- 返回：
```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "expires_in": 7200
}
```

### 4.2 账户管理

#### GET `/accounts`
- 说明：查询当前用户全部账户。

#### POST `/accounts`
- 请求体：
```json
{
  "name": "招商银行储蓄卡",
  "account_type": "bank",
  "currency": "CNY",
  "initial_balance": "10000.00"
}
```

#### PATCH `/accounts/{account_id}`
- 说明：更新账户名称、状态等非关键字段。

### 4.3 资产与持仓

#### GET `/assets/distribution`
- 说明：按资产类别返回占比和金额。

#### GET `/positions`
- 说明：查询基金/股票持仓。
- 查询参数：`asset_type`, `symbol`, `page`, `page_size`。

### 4.4 交易与转账

#### POST `/transactions`
- 请求体（收入示例）：
```json
{
  "type": "income",
  "account_id": 1,
  "amount": "12000.00",
  "occurred_at": "2026-04-30T09:00:00+08:00",
  "category": "salary",
  "note": "4月工资"
}
```

#### POST `/transfers`
- 请求体：
```json
{
  "from_account_id": 1,
  "to_account_id": 2,
  "amount": "3000.00",
  "occurred_at": "2026-04-30T10:00:00+08:00",
  "note": "银行转入支付宝"
}
```

#### GET `/transactions`
- 说明：分页查询交易历史。
- 查询参数：`type`, `account_id`, `asset_type`, `start_date`, `end_date`, `page`, `page_size`。

### 4.5 收益与报表

#### GET `/reports/pnl`
- 说明：收益统计（储蓄、基金、股票分开展示）。
- 查询参数：`start_date`, `end_date`, `granularity=day|week|month`。

#### GET `/reports/net-worth`
- 说明：净资产时间序列。

### 4.6 AI 辅助分析

#### POST `/ai/analyze`
- 请求体：
```json
{
  "question": "本月收益为什么下降？",
  "start_date": "2026-04-01",
  "end_date": "2026-04-30"
}
```
- 返回：
```json
{
  "analysis": "文本分析结果",
  "suggestions": [
    "控制单一资产过高仓位",
    "减少高波动标的短线频繁交易"
  ],
  "evidence": [
    "股票类资产回撤超过基金类",
    "本月大额支出提高现金流压力"
  ]
}
```

## 5. 数据库表结构 SQL（PostgreSQL）

> 说明：开发与生产统一使用 PostgreSQL。以下 SQL 为 PostgreSQL 标准语法。

```sql
-- 1) 用户表
CREATE TABLE IF NOT EXISTS users (
  id BIGSERIAL PRIMARY KEY,
  username VARCHAR(64) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  status SMALLINT NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2) 账户表
CREATE TABLE IF NOT EXISTS accounts (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  name VARCHAR(128) NOT NULL,
  account_type VARCHAR(32) NOT NULL, -- bank/alipay/wechat/broker/fund/cash
  currency VARCHAR(8) NOT NULL DEFAULT 'CNY',
  balance NUMERIC(18, 2) NOT NULL DEFAULT 0,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_accounts_user_id ON accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_accounts_type ON accounts(account_type);

-- 3) 资产标的表
CREATE TABLE IF NOT EXISTS assets (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  asset_type VARCHAR(16) NOT NULL, -- fund/stock
  symbol VARCHAR(32) NOT NULL,
  name VARCHAR(128) NOT NULL,
  market VARCHAR(32),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(user_id, asset_type, symbol)
);

CREATE INDEX IF NOT EXISTS idx_assets_user_id ON assets(user_id);

-- 4) 交易流水表
CREATE TABLE IF NOT EXISTS transactions (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  type VARCHAR(32) NOT NULL, -- income/expense/transfer/buy/sell/dividend
  account_id BIGINT REFERENCES accounts(id),
  asset_id BIGINT REFERENCES assets(id),
  amount NUMERIC(18, 2) NOT NULL CHECK (amount >= 0),
  quantity NUMERIC(18, 6), -- 买卖时使用
  price NUMERIC(18, 6),    -- 买卖时使用
  fee NUMERIC(18, 2) NOT NULL DEFAULT 0,
  category VARCHAR(64),    -- salary/urgent/transfer/...
  note TEXT,
  occurred_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_transactions_user_time ON transactions(user_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_type ON transactions(type);
CREATE INDEX IF NOT EXISTS idx_transactions_account ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_transactions_asset ON transactions(asset_id);

-- 5) 转账明细表（与 transactions.type=transfer 配套）
CREATE TABLE IF NOT EXISTS transfer_records (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  transaction_id BIGINT NOT NULL UNIQUE REFERENCES transactions(id),
  from_account_id BIGINT NOT NULL REFERENCES accounts(id),
  to_account_id BIGINT NOT NULL REFERENCES accounts(id),
  amount NUMERIC(18, 2) NOT NULL CHECK (amount > 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (from_account_id <> to_account_id)
);

CREATE INDEX IF NOT EXISTS idx_transfer_user_id ON transfer_records(user_id);

-- 6) 持仓表
CREATE TABLE IF NOT EXISTS positions (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  asset_id BIGINT NOT NULL REFERENCES assets(id),
  quantity NUMERIC(18, 6) NOT NULL DEFAULT 0,
  avg_cost NUMERIC(18, 6) NOT NULL DEFAULT 0,
  realized_pnl NUMERIC(18, 2) NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(user_id, asset_id)
);

CREATE INDEX IF NOT EXISTS idx_positions_user_id ON positions(user_id);

-- 7) 收支标签表（可选）
CREATE TABLE IF NOT EXISTS income_expense_tags (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  tag_key VARCHAR(64) NOT NULL,
  tag_name VARCHAR(128) NOT NULL,
  direction VARCHAR(16) NOT NULL, -- income/expense/both
  UNIQUE(user_id, tag_key)
);
```

## 6. 关键校验与规则

### 6.1 余额校验
- 任何扣减余额的操作（转出、买入、支出）都必须先校验可用余额。
- 余额变动与交易记录写入必须在同一事务。

### 6.2 持仓校验
- 卖出前必须校验持仓数量充足。
- 持仓数量不得小于 0。

### 6.3 幂等与重复提交
- 对外写接口建议支持 `idempotency_key`，防止重复提交造成重复入账。

## 7. AI/RAG 设计建议

### 7.1 MVP 方案
- 不引入向量数据库。
- 直接从结构化数据生成分析上下文（如近 30 天收益、资产占比变化、大额资金波动）后调用 LLM。

### 7.2 何时引入 RAG
- 当积累了大量非结构化文档（投资日志、策略文档、复盘文本）且有“知识问答”需求时再引入。
- 例如：问“过去三个月我在新能源主题上采取了什么策略，效果如何？”

### 7.3 Provider 抽象
- 统一接口：`generate_analysis(prompt, context, config)`。
- 配置项：模型名称、温度、超时、重试、API Key（环境变量读取）。

## 8. 测试建议

### 8.1 单元测试
- 收益计算（买卖、手续费、已实现收益）。
- 平均成本与持仓更新逻辑。

### 8.2 集成测试
- 转账事务一致性（任一步失败均回滚）。
- 买入/卖出后余额和持仓一致性。

### 8.3 API 测试
- 鉴权成功/失败路径。
- 分页、筛选、时间范围查询准确性。

## 9. 实施顺序（开发任务拆分）

1. 数据层：建表 + repository 基础 CRUD。
2. 业务层：账户、交易、转账、持仓服务。
3. 接口层：认证、账户、交易、报表 API。
4. 前端层：资产总览、交易录入、历史查询。
5. AI 层：provider 抽象 + 分析接口。

## 10. 数据库迁移与环境配置

### 10.1 迁移工具
- 使用 Alembic 管理 schema 版本，禁止手工直接改生产库结构。
- 每次模型变更后生成迁移脚本并执行升级。

### 10.2 建议命令
- 初始化（首次）：
  - `alembic init migrations`
- 生成迁移：
  - `alembic revision --autogenerate -m "init financial tables"`
- 执行迁移：
  - `alembic upgrade head`
- 回滚一步：
  - `alembic downgrade -1`

### 10.3 环境变量约定
- `DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>:5432/<db_name>`
- `APP_ENV=dev|test|prod`

### 10.4 开发环境建议
- 本地通过 Docker 启动 PostgreSQL，确保与生产方言一致。
- 建议固定主版本（例如 PostgreSQL 16），减少环境差异。

---

如无特殊约束，优先实现“可验证正确性”的账务核心，再迭代可视化和 AI 能力。
