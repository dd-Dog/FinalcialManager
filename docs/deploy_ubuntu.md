# Ubuntu 云服务器部署简要指南

面向单机部署：一台 Ubuntu（建议 22.04 LTS 及以上）上运行 **PostgreSQL + FastAPI 后端 + Streamlit 前端**。端口与路径可按实际环境修改。

## 1. 服务器准备

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip git postgresql postgresql-contrib nginx
```

若结束后弹出 **needrestart** 对话框（“Daemons using outdated libraries” / 询问要重启哪些服务）：光标移到 **`<Ok>`** 回车即可；默认已勾选项一般不用改，表示让这些服务加载刚更新的库。**`<Cancel>`** 只是跳过本次重启提示，部分进程仍用旧库，不如确认 Ok。若你用 Docker 且列表里 `docker.service` 未勾选，可勾上再 Ok，或稍后执行 `sudo systemctl restart docker`。通过 SSH 连接时，重启 `ssh.service` 通常**不会**断开当前会话；若仍担心，可先在云控制台再开一条会话再按 Ok。

（若使用云厂商托管数据库，可只装本机所需组件，把 `DATABASE_URL` 指向托管实例。）

## 2. PostgreSQL 与数据库

```bash
sudo -u postgres psql -c "CREATE USER fmuser WITH PASSWORD '请改为强密码';"
sudo -u postgres psql -c "CREATE DATABASE financial_manager OWNER fmuser;"
```

在应用目录创建 `.env`（不要提交到 Git，仓库已忽略 `.env`）：

```bash
cp .env.example .env
nano .env   # 修改 DATABASE_URL、JWT_SECRET_KEY 等
```

`DATABASE_URL` 示例：

```text
postgresql+psycopg://fmuser:你的密码@127.0.0.1:5432/financial_manager
```

## 3. 应用代码与依赖

```bash
cd /opt   # 或你喜欢的目录
sudo git clone <你的仓库地址> FinancialManager
sudo chown -R $USER:$USER FinancialManager
cd FinancialManager

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

## 4. 数据库结构（迁移）

```bash
source .venv/bin/activate
alembic upgrade head
```

发版后若出现 **财产总览或持仓相关接口 500**，且 API 日志中有 **`opened_at`** / **`UndefinedColumn`**：说明库结构落后于代码。在应用目录执行上条 `alembic upgrade head`（会应用含 `positions.opened_at` 在内的迁移；若启动脚本已自动加过该列，迁移内已做存在性判断，可安全执行），然后 **`sudo systemctl restart financial-manager-api.service`**。仍失败时用数据库超级用户执行：  
`\d positions`（`psql`）确认是否已有 `opened_at`；并查看 **`journalctl -u financial-manager-api.service -n 100 --no-pager`** 中的完整报错。

## 5. 启动后端（API）

开发验证可手动：

```bash
source .venv/bin/activate
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### 5.1 生产：用 systemd 常驻（推荐）

仓库内已提供单元模板（默认：**本机 `127.0.0.1:8123`** + 项目路径 **`/opt/FinancialManager`**，与下文 Nginx 反代一致）：

- `deploy/systemd/fm-api.service` — uvicorn  
- `deploy/systemd/fm-webui.service` — Streamlit  

**安装步骤（在服务器上执行，路径按实际修改）：**

1. **先停掉**当前手动起的 `uvicorn` / `streamlit`（避免占端口）。  
2. 复制并改路径与运行用户（示例把项目放在 `/home/ubuntu/FinancialManager`，用户 `ubuntu`）：

```bash
APP=/home/ubuntu/FinancialManager
sudo cp "$APP/deploy/systemd/fm-api.service" /etc/systemd/system/
sudo cp "$APP/deploy/systemd/fm-webui.service" /etc/systemd/system/
sudo sed -i "s|/opt/FinancialManager|$APP|g" /etc/systemd/system/fm-api.service /etc/systemd/system/fm-webui.service
sudo sed -i 's/^User=.*/User=ubuntu/;s/^Group=.*/Group=ubuntu/' /etc/systemd/system/fm-api.service /etc/systemd/system/fm-webui.service
```

若目录在 **`/root/...`** 且仍用 **`User=www-data`**，`www-data` 可能**无权限读代码与 `.env`**，需改为 **`User=root`**（自用可接受）或 **`chown -R www-data:www-data`** 项目目录。

**示例：项目在 `/root/bianjb/FinancialManager`，用 root 跑，单元名为 `financial-manager-*.service`：**

```bash
APP=/root/bianjb/FinancialManager
sudo sed -i "s|/opt/FinancialManager|$APP|g" /etc/systemd/system/financial-manager-api.service /etc/systemd/system/financial-manager-webui.service
sudo sed -i 's/^User=.*/User=root/;s/^Group=.*/Group=root/' /etc/systemd/system/financial-manager-api.service /etc/systemd/system/financial-manager-webui.service
# Web 单元里 After= 若仍写 fm-api.service，改成与你实际的 API 单元名一致：
sudo sed -i 's/fm-api\.service/financial-manager-api.service/g' /etc/systemd/system/financial-manager-webui.service
```

**若未使用 `.venv`、而是用 conda/virtualenv 其它路径**：`ExecStart` 里的 `uvicorn` / `streamlit` 必须改为该环境下的绝对路径（在已激活环境中执行 `which uvicorn`、`which streamlit` 查看）。

3. 若 API 端口不是 **8123**，编辑 `fm-api.service` 里 `ExecStart` 的 `--port`。  
4. 启用并启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now fm-api.service fm-webui.service
sudo systemctl status fm-api.service fm-webui.service --no-pager
```

5. 看日志：

```bash
journalctl -u fm-api.service -f
journalctl -u fm-webui.service -f
```

6. 发版重启：

```bash
sudo systemctl restart fm-api.service fm-webui.service
```

仅本机监听 `127.0.0.1` 时，建议前面加 **Nginx** 反代 HTTPS，对外只暴露 443。

## 6. Streamlit 与 `.env`（FM_API_BASE）

`.env` 中 **`FM_API_BASE`**：前后端**同一台机**时建议 **`http://127.0.0.1:8123/api/v1`**（与 `fm-api.service` 端口一致，避免本机访问公网 IP 超时）。若 Streamlit 单独在另一台机，则填对端可访问的 API 根 URL（含 `https` 与域名时与 Nginx 一致）。

**端口**：若 uvicorn 监听的是 **8123** 等非常规端口，且**没有** Nginx 把 80/443 转到该端口，则浏览器直连 API 时 URL 必须带端口。

**根路径**：`GET /api/v1` 会 **307** 到 **`/api/v1/`**；自检可用 **`GET /api/v1/health`** 或 **`/docs`**。

再用 Nginx 把 `https://你的域名/` 反代到 `http://127.0.0.1:8501`（按需配置 WebSocket 相关头，参见 Streamlit 反向代理文档）。

## 7. HTTPS（Nginx + Let’s Encrypt，推荐生产）

思路：**uvicorn、Streamlit 仍只监听本机**（如 `127.0.0.1:8123`、`127.0.0.1:8501`），对外由 **Nginx 监听 443** 终止 TLS，再反代到本机 HTTP。

### 7.1 前置条件

1. 已有一个**域名**（如 `fm.example.com`），DNS **A 记录**指向该云主机公网 IP。  
2. 云安全组与本机防火墙放行 **80、443**（Let’s Encrypt 校验证书常用 **80**）。  
3. 后端、前端 systemd 里已改为 **`127.0.0.1`** 监听（上文示例），避免与 Nginx 抢公网端口。

### 7.2 Nginx 站点配置示例

新建 `/etc/nginx/sites-available/financial-manager`（域名与端口按你实际修改；API 以 **8123** 为例）：

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80;
    listen [::]:80;
    server_name fm.example.com;

    # API（与 FastAPI 的 /api/v1 前缀一致；用 /api/v1 可匹配有无尾斜杠）
    location /api/v1 {
        proxy_pass http://127.0.0.1:8123;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header Cookie $http_cookie;
    }

    # Swagger / OpenAPI（在应用根路径，不在 /api/v1 下）
    location /docs {
        proxy_pass http://127.0.0.1:8123/docs;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header Cookie $http_cookie;
    }
    location /openapi.json {
        proxy_pass http://127.0.0.1:8123/openapi.json;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header Cookie $http_cookie;
    }

    # Streamlit（根路径放最后）
    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header Cookie $http_cookie;
        proxy_buffering off;
        proxy_read_timeout 86400;
    }
}
```

若 WebUI 刷新后总回登录页，请确认上述 **`location /`**（及 `/api/v1`）中已包含 **`proxy_set_header Cookie $http_cookie;`** 与 **`X-Forwarded-Host`**；Streamlit 侧 `.env` 中 **`FM_API_BASE`** 须为浏览器同源 HTTPS 地址（如 `https://你的域名/api/v1`）。

启用并重载：

```bash
sudo ln -sf /etc/nginx/sites-available/financial-manager /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 7.3 申请证书（Certbot）

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d fm.example.com
```

按提示选择「将 HTTP 重定向到 HTTPS」。完成后 Nginx 会自动加上 `listen 443 ssl` 等配置。证书默认会自动续期（`certbot.timer`）。

### 7.4 应用侧 `.env`

与浏览器访问的域名一致（**https**，且无多余端口时不必写 `:443`）：

```text
FM_API_BASE=https://fm.example.com/api/v1
```

修改后执行：`sudo systemctl restart fm-webui`（以及若后端也依赖对外 URL，一并重启 `fm-api`）。

### 7.5 自检

- 浏览器打开：`https://fm.example.com/`（Streamlit）、`https://fm.example.com/api/v1/health`（应返回 JSON）。  
- 官方对 Nginx + Streamlit 的说明可参考：[Streamlit — Deploy behind a reverse proxy](https://docs.streamlit.io/knowledge-base/deploy/deploy-nignx)（注意文档中的路径与版本差异，以你机上 `nginx -t` 为准）。

---

## 8. 防火墙（可选）

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

若暂时不经过 Nginx、直接暴露端口，再按需放行对应端口（不推荐生产环境长期直连 Streamlit 端口对外）。

---

## 升级与数据不丢失

数据主要在 **PostgreSQL**；升级代码时按下面顺序可最大限度避免丢数据。

### 升级前必做：备份

```bash
# 逻辑备份（推荐定期做，升级前必做一次）
pg_dump -h 127.0.0.1 -U fmuser -d financial_manager -Fc -f financial_manager_$(date +%Y%m%d_%H%M).dump
```

将 `.dump` 文件拷到安全位置（另一台机器、对象存储等）。

### 升级步骤（典型）

1. **备份数据库**（上条 `pg_dump`）。
2. 维护窗口内 **停止** Web UI 与 API（避免迁移过程中有写入）：  
   `sudo systemctl stop fm-webui fm-api`
3. `git pull` 获取新版本（或发布物解压覆盖）。
4. `source .venv/bin/activate && pip install -r requirements.txt`
5. **执行迁移**：`alembic upgrade head`（仅在有新迁移文件时也会升级 schema；无新迁移则不变）。
6. 检查 `.env.example` 是否有新增变量，按需合并到服务器 `.env`。
7. `sudo systemctl start fm-api fm-webui`

### 若迁移后异常需要回滚

- **应用代码**：`git checkout` 到上一版本标签/提交，重启服务。
- **数据库**：用升级前的 `pg_dump` 做 **还原**（会覆盖当前库，仅在确认必须回滚时执行）：  
  `pg_restore --clean -d financial_manager ...dump`

Alembic 一般不提供安全的「自动 downgrade 生产数据」；**以备份恢复为主**。

### 长期建议

- 对生产库做 **自动定时备份**（每日 `pg_dump` + 保留天数）。
- 重大版本先在 **预发环境** 跑一遍迁移与冒烟测试，再上生产。
- **JWT_SECRET_KEY**、数据库密码等只放在服务器 `.env`，勿写入仓库。

---

更细的 API 冒烟步骤可参考仓库内 `docs/quick_api_smoke_test.md`。
