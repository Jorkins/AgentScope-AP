# AgentScope-AP Backend

多 Agent 平台后端。以 AgentScope `create_app` 为运行时内核，外加 `app/platform` 平台壳（认证 / 多租户 / 缓存 / 平台路由）。

## 运行

```bash
# 在仓库根先起依赖：docker compose up -d postgres redis milvus minio minio-init
# 并配置根 .env（至少一个模型 API Key）

cd backend
uv venv .venv
uv pip install --python .venv -e .

# 启动（Windows）
.venv/Scripts/python -m app.main
# 或类 Unix
.venv/bin/python -m app.main
```

服务监听 `http://localhost:8000`，接口文档 `http://localhost:8000/docs`。

## 结构

- `app/main.py`：装配 storage(PostgreSQL) / message_bus(Redis) / vector_store(Milvus，Qdrant 可回滚) / blob(MinIO/S3) / workspace(本地隔离) / 混合知识库，并把平台壳注入 `create_app`。
- `app/config.py`：集中配置，读取根 `.env` 与 `backend/.env`。
- `app/platform/`：平台壳
  - `models.py`：`ap_users` / `ap_tenants` / `ap_memberships` / `ap_resource_shares`
  - `auth.py`：`AuthService`(JWT) + `JwtAuthMiddleware`(注入 X-User-ID)
  - `tenant.py`：`TenantResourceAccessPolicy`
  - `cache.py`：`RedisCache`
  - `routes.py`：`/api/platform/auth/*`、`/tenants`、`/shares`

## 平台 API 速览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/platform/auth/register` | 注册（自动建个人租户），返回 token |
| POST | `/api/platform/auth/login` | 登录，返回 token |
| GET | `/api/platform/auth/me` | 当前用户与租户 |
| POST | `/api/platform/tenants` | 创建租户 |
| GET | `/api/platform/tenants` | 我的租户 |
| POST | `/api/platform/shares` | 分享资源给租户/用户 |
| GET | `/api/platform/shares/accessible` | 我能访问的共享资源 |

## 快速自测（curl）

```bash
# 注册
curl -X POST http://localhost:8000/api/platform/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"secret123"}'
# => {"access_token":"...","username":"alice","tenant_id":"..."}

# 用 token 调 AgentScope 接口（中间件会注入 X-User-ID=alice）
curl http://localhost:8000/knowledge_bases/ -H "Authorization: Bearer <token>"
```

## 阶段开关

- `AUTH_ENABLED=true`（默认，阶段2）：除公开路径外均需 JWT。
- `AUTH_ENABLED=false`（阶段1）：无 token 时透传 `X-User-ID`，便于本地联调。
