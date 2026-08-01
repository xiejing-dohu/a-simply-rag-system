# 智能 RAG 系统后端架构说明

本目录是 FastAPI 后端，负责认证与权限、用户隔离、模型发现、SSE 流式聊天、
Token 配额、文档处理、Embedding、Milvus 检索以及 MySQL 知识库元信息管理。
Python 依赖和虚拟环境统一由 `uv` 管理。

## 1. 架构概览

```text
Vue 前端
  │ REST / SSE
  ▼
FastAPI（app/main.py 应用工厂）
  ├─ api/：认证、聊天、知识库、模型与系统路由
  ├─ services/：模型发现、OpenAI-compatible 流式调用
  ├─ schemas/：按领域划分的请求/响应契约
  ├─ Redis：Refresh Token、登录锁定、任务唤醒提示
  ├─ knowledge_repository.py ── SQLAlchemy async ── MySQL
  ├─ knowledge_runtime.py ───── 文档解析 / Embedding ── Milvus
  └─ rag/retriever.py ───────── Dense / MMR / BM25 + RRF
                                                    │
Milvus ── etcd（内部元数据）+ MinIO（对象数据）
```

当前存储边界：

| 数据 | 存储位置 | 重启后 |
| --- | --- | --- |
| 用户、密码哈希、角色 | MySQL `users` | 保留 |
| 会话、消息、消息 RAG 上下文 | MySQL `conversations/messages` | 保留 |
| Token 累计和 5 小时/周窗口 | MySQL `users` | 保留 |
| Refresh Token、失败锁定 | Redis | TTL 到期或主动吊销 |
| 文档任务状态 | MySQL `document_tasks` | 保留并可恢复 |
| 文档待处理队列 | MySQL `document_tasks` | 可靠队列、租约恢复 |
| 知识库、Collection 映射 | MySQL `knowledge_bases` | 保留 |
| 文档处理元信息 | MySQL `knowledge_documents` | 保留 |
| 切片文本、字段、向量 | Milvus | 保留 |
| Milvus 内部元数据和对象 | etcd / MinIO | Docker Volume 保留 |

Access Token 为短期 JWT，不在服务端保存；Refresh Token 指纹保存在 Redis，
可独立吊销。MySQL 使用行锁更新 Token 窗口，避免并发请求覆盖统计。

## 2. 目录与模块职责

```text
Backend/
├── .env                         # 本地运行配置，不提交密钥
├── pyproject.toml               # uv 项目及依赖声明
├── uv.lock                      # 可复现依赖锁
├── Dockerfile                   # API / Worker 共用运行镜像
├── docker-compose.yml           # 数据服务、迁移、API、独立 Worker
├── alembic.ini
├── migrations/                  # Alembic 版本化数据库迁移
├── tests/                       # HTTP 与 Worker 集成测试
├── README.md
└── app/
    ├── main.py                  # 应用工厂、生命周期、中间件、Router 注册
    ├── api/
    │   ├── dependencies.py      # JWT 当前用户和管理员依赖
    │   ├── auth.py              # 认证、用户、配额路由
    │   ├── chat.py              # 会话、RAG 设置、SSE 路由
    │   ├── knowledge.py         # 知识库、任务和 Milvus 浏览路由
    │   ├── model.py             # 模型发现路由
    │   └── system.py            # 根路由和健康检查
    ├── state_repository.py      # 用户、会话、消息、Token MySQL 仓储
    ├── knowledge_repository.py  # MySQL 知识库/文档仓储和序列化
    ├── knowledge_runtime.py     # 解析、Token 切片、Embedding、Milvus CRUD
    ├── document_tasks.py        # MySQL 租约、Redis 唤醒和异步入库
    ├── vector_outbox.py         # Milvus Saga/Outbox Worker
    ├── worker.py                # 独立 Worker 进程入口
    ├── db/
    │   ├── mysql.py             # SQLAlchemy 异步引擎和 Session
    │   └── redis.py             # Redis 异步客户端
    ├── models/
    │   ├── knowledge_base.py    # 当前启用的知识库 ORM 模型
    │   ├── knowledge_document.py# 当前启用的文档 ORM 模型
    │   ├── user.py
    │   ├── conversation.py
    │   ├── message.py
    │   └── document_task.py     # 均为当前运行模型
    ├── rag/
    │   └── retriever.py         # 实际 RAG 检索、预算裁剪、Prompt 格式化
    ├── core/                    # 配置、安全和共享异常
    ├── schemas/                 # auth/chat/knowledge Pydantic 契约
    └── services/
        ├── model_catalog.py     # 模型发现、过滤和缓存
        └── chat_completion.py   # 上游 SSE 调用、重试和解析
```

当前运行入口仍为 `app.main:app`，但 `main.py` 只负责组装。新增 HTTP 接口放在
`api/`，输入输出契约放在 `schemas/`，外部模型调用放在 `services/`，存储访问放在
Repository 或任务模块，避免再次把业务堆进入口文件。

## 3. 启动生命周期

数据库结构只通过 Alembic 管理。FastAPI 启动时校验数据库是否位于迁移 `head`，
不再执行 `create_all` 或运行时 DDL；版本落后会停止并提示执行
`uv run alembic upgrade head`。迁移完成后 API 只负责写入默认开发管理员。

文档处理和 Milvus Outbox 由 `python -m app.worker` 独立运行。API 与 Worker 可
分别扩容、重启；FastAPI 进程不会再消费后台任务。

Milvus Collection 不在启动时全量重建；知识库通过 MySQL 中的
`collection_name` 恢复与已有 Collection 的映射。

## 4. 认证、权限与隔离

### 认证

- 密码使用 PBKDF2-SHA256 加盐哈希，不保存明文。
- 登录签发有过期时间的 Access JWT 和 Refresh JWT。
- Refresh Token 指纹保存在 Redis，可由 `/auth/logout` 主动吊销。
- 用户名在注册、登录和 Redis 锁键中统一执行首尾去空格及小写化；大小写变体不能绕过锁定。
- 连续 3 次密码错误后用 Redis TTL 按规范化用户名锁定 5 分钟。
- 登录成功后清除该用户名的失败记录。
- 停用用户返回 HTTP 403。

默认管理员密码仍仅供本地开发，生产部署必须修改。

### 角色

- 注册用户固定为 `employee`。
- 默认 `admin` 是 `is_root_admin=true` 的系统管理员，不可降级或停用。
- 只有系统管理员可以授予或撤销 `admin` 身份。
- 后续被提升的管理员不能更改任何用户身份，也不能修改系统管理员账户。
- 管理员可管理普通用户启停状态、Token 上限和窗口重置。

### 聊天隔离

每个会话和消息都带服务端 `user_id`。读取会话、读取消息、发送消息、删除会话、
切换模型和保存 RAG 设置前都会通过 `owned_conversation()` 校验资源归属。
响应会移除内部 `user_id`，客户端无法借助请求参数切换所属用户。

## 5. 模型配置与发现

后端从 `Backend/.env` 读取 OpenAI-compatible 配置：

```env
OPENAI_API_KEY=替换为实际密钥
OPENAI_API_BASE=https://example.com/compatible-mode/v1
DEFAULT_MODEL=qwen-plus-latest
EMBEDDING_MODEL=text-embedding-v4

# 可选
AVAILABLE_MODELS=qwen-plus-latest,qwen-max-latest
MODEL_PROVIDER=DashScope
```

`GET /models/` 调用上游 `${OPENAI_API_BASE}/models`：

1. 过滤 embedding、rerank、图片、音频、OCR 等非聊天模型；
2. 如果配置了 `AVAILABLE_MODELS`，再与允许列表求交集；
3. 缓存结果 5 分钟；
4. 上游探测失败时回退到 `.env` 中的模型；
5. `refresh=true` 可强制重新探测。

API Key 不会通过任何接口返回前端。聊天通过上游
`${OPENAI_API_BASE}/chat/completions`，请求 `stream=true` 和
`stream_options.include_usage=true`。

## 6. 流式聊天与 Token 配额

聊天接口：

```http
POST /chat/conversations/{conversation_id}/messages/stream
Content-Type: application/json
Authorization: Bearer <token>
```

处理顺序：

```text
认证与会话归属
  → 刷新/检查 5 小时与 7 天 Token 窗口
  → 可选执行 RAG 并构造 system 上下文
  → 保存当前用户消息
  → 调用上游流式聊天接口
  → 转发文本增量
  → 读取上游最终 usage
  → 按当前用户 ID 记录 Token
  → 保存助手完整消息及 rag_context
```

SSE 协议：

```text
event: rag
data: {...RAG 召回信息...}

data: {"content":"文本增量"}

event: error
data: {"message":"错误信息"}

data: [DONE]

```

只有启用 RAG 时才发送 `rag` 事件。响应头包含 `Cache-Control: no-cache` 和
`X-Accel-Buffering: no`，避免代理缓冲。

Token 按用户统计：

- 累计 `input_tokens_used`、`output_tokens_used`、`total_tokens_used`；
- 当前 5 小时窗口用量；
- 当前 7 天窗口用量；
- 两个窗口分别支持正整数上限或 `null`（无限）。

达到任一上限时在调用模型前返回 429。窗口到期自动清零，管理员也可用
`five_hour`、`weekly` 或 `all` 手动重置窗口；累计用量不会随窗口重置而清除。

## 7. 异步文档处理和入库架构

支持 `.docx`、`.xlsx`、`.xls`、`.csv`、`.txt`、`.md` 和 `.pdf`，单文件最大
30 MB。旧版 `.doc` 不受支持，需要先转换为 `.docx`。

上传接口保存文件并返回 HTTP 202 和 `task_id`，独立 Worker 异步执行：

```text
管理员上传 multipart 文件 → MySQL 创建 document_tasks
  → Redis 提示有新任务（提示丢失不影响可靠性）
  → MySQL `FOR UPDATE SKIP LOCKED` 原子领取任务租约
  → 校验知识库、大小、扩展名、切片参数
  → 提取文本
  → Excel 拼接全部工作表、字段和数据行
  → tiktoken 按 chunk_tokens / overlap_tokens 切片
  → 调用 EMBEDDING_MODEL 生成知识库指定维度向量
  → 写入对应 Milvus Collection
  → MySQL 写入文档元信息
  → 更新知识库 file_count / chunk_count
  → 任务进度 100%，临时文件删除
```

任务阶段和进度可通过 `GET /knowledge-bases/tasks/{task_id}` 查询。Worker
每 30 秒更新租约心跳；进程异常退出后，其他 Worker 会在租约过期后重新领取。
Worker 被取消时会先把任务恢复为 `queued` 并保留临时文件，下一实例可继续处理；
只有任务完成或确定失败后才删除临时文件。
`DOCUMENT_WORKER_CONCURRENCY` 控制单个 Worker 服务内的文档并发数。

切片参数：

- `chunk_tokens`：64–8192；
- `overlap_tokens`：0–4096，且必须小于 `chunk_tokens`。

DashScope `text-embedding-v4` 当前配置支持 64、128、256、512、768、1024、
1536、2048 维。后端通过 `/knowledge-bases/embedding-config` 将实际模型、
服务商、可选维度和扩展名返回给前端。

Milvus Collection 主要字段：

| 字段 | 说明 |
| --- | --- |
| `id` | 由 `task_id + chunk_index` 生成的稳定 INT64 主键 |
| `document_id` | 文档入库任务 UUID |
| `text` | 切片原文 |
| `document_name` | 来源文件 |
| `source_type` | 来源扩展名 |
| `chunk_index` | 文件内切片序号 |
| `token_count` | 切片 Token 数 |
| `uploaded_by` | 上传用户 ID |
| `created_at` | 写入时间 |
| `embedding` | 固定维度向量 |

### 跨存储一致性

知识库创建和删除采用 Saga + Transactional Outbox。业务状态和
`vector_operations` 在同一个 MySQL 事务中提交，后台 Worker 直接轮询 MySQL，
再幂等创建或删除 Milvus Collection：

- 创建：`creating → active`，Collection 创建成功后才允许上传和检索；
- 删除：`active → deleting`，先停止新请求，等待已有文档任务结束，确认 Milvus
  Collection 已删除后，才物理删除 MySQL 知识库及其级联记录；
- 操作使用唯一幂等键、行锁领取、指数退避重试和进程中断恢复；
- 每分钟对账 `active` 记录与 Collection；发现 Collection 丢失时标记
  `inconsistent`，不会静默创建一个空集合掩盖数据丢失。

MySQL 与 Milvus 仍不支持原生分布式事务，因此保证的是可恢复的最终一致性。
文档切片使用稳定主键和 Milvus `upsert`，MySQL 文档元信息使用唯一
`ingestion_id`，Worker 在任意阶段重试都不会重复增加切片或统计；最终失败仍会按
稳定主键执行补偿删除。

## 8. RAG 检索架构

`app/rag/retriever.py` 提供三种模式：

| 模式 | 实现 | 适用场景 |
| --- | --- | --- |
| `semantic` | Dense 候选 + MMR 重排 | 需要语义相关且减少重复切片 |
| `dense` | Milvus COSINE 直接排名 | 单纯按向量相似度检索 |
| `hybrid` | Milvus Dense + BM25 Sparse，经 RRF 融合 | 语义和精确关键词 |

Milvus 2.5 新 Collection 包含 `embedding` Dense 字段、`sparse` 字段和服务端
BM25 Function。旧 Collection 没有 `sparse` 字段时自动回退到本地 BM25。
配置 `RERANK_PROVIDER=dashscope` 后，初筛候选还会调用 `qwen3-rerank` 精排。

检索流程：

```text
用户问题 → 问题 Embedding → 候选召回/排序
        → 按 max_retrieval_tokens 装入
        → 必要时截断最后一个切片
        → format_rag_prompt()
        → 作为 system 消息注入聊天模型
```

`max_retrieval_tokens` 范围为 128–16000。返回来源包含文件名、切片序号、原文、
Token 数、相关分数及是否被截断。Prompt 要求模型依据资料回答并使用
`[资料 N]` 标记引用；未找到资料时应明确说明缺少知识库依据。

## 9. 数据服务

`docker-compose.yml` 同时支持数据层和后端生产拓扑：

| 服务 | 镜像/版本 | 本机端口 | 用途 |
| --- | --- | --- | --- |
| MySQL | `mysql:8.0` | 3306 | 业务元信息 |
| Redis | `redis:7.4-alpine` | 6379 | 安全状态和任务唤醒 |
| Milvus | `milvusdb/milvus:v2.5.18` | 19530、9091 | Dense/Sparse 向量 |
| etcd | `quay.io/coreos/etcd:v3.5.5` | 容器网络 | Milvus 元数据 |
| MinIO | `minio/minio` | 9000、9001 | Milvus 对象存储 |
| migrate | 项目镜像 | 无 | 一次性执行 Alembic |
| api | 项目镜像 | 8000 | FastAPI，仅处理请求 |
| worker | 项目镜像 | 无 | 文档和 Milvus Outbox |

所有服务使用命名 Volume，并配置 `restart: unless-stopped`。

## 10. 环境变量

| 变量 | 说明 | 常用本地值 |
| --- | --- | --- |
| `MYSQL_HOST` | MySQL 主机 | `127.0.0.1` |
| `MYSQL_PORT` | MySQL 端口 | `3306` |
| `MYSQL_USER` | MySQL 用户 | `root` |
| `MYSQL_PASSWORD` | MySQL 密码 | 必填 |
| `MYSQL_DATABASE` | 数据库名 | `rag_system` |
| `MILVUS_HOST` | Milvus 主机 | `127.0.0.1` |
| `MILVUS_PORT` | Milvus gRPC 端口 | `19530` |
| `REDIS_URL` | 带密码的 Redis 地址 | 必填 |
| `OPENAI_API_KEY` | 模型服务密钥 | 必填 |
| `OPENAI_API_BASE` | OpenAI-compatible `/v1` 根地址 | 必填 |
| `DEFAULT_MODEL` | 默认聊天模型 | 必填 |
| `EMBEDDING_MODEL` | 向量模型 | 必填 |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh Token 有效天数 | `7` |
| `DOCUMENT_WORKER_CONCURRENCY` | 单个 Worker 文档并发数 | `2` |
| `RERANK_PROVIDER` | `none` 或 `dashscope` | `none` |
| `RERANK_MODEL` | 重排模型 | `qwen3-rerank` |
| `RERANK_API_URL` | DashScope `/reranks` 地址 | 启用时必填 |
| `AVAILABLE_MODELS` | 可选聊天模型允许列表 | 可选 |
| `MODEL_PROVIDER` | 前端展示的服务商名称 | 可选 |

Compose 中 MySQL、Redis 和 MinIO 密码均从 `Backend/.env` 读取，不在仓库中
保存真实凭据。

## 11. 启动、检查与停止

全部使用 Docker 启动时，迁移会先执行，成功后 API 和 Worker 才启动：

```powershell
cd D:\智能rag系统\Backend
docker compose up -d --build
docker compose ps
```

本地使用 uv 开发时，先启动数据服务、执行迁移并启动 API：

```powershell
docker compose up -d mysql redis etcd minio milvus
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

另开一个 PowerShell 启动独立 Worker：

```powershell
cd D:\智能rag系统\Backend
uv run python -m app.worker
```

运行端到端与集成测试：

```powershell
uv run --group dev pytest -q
uv run alembic check
```

检查地址：

- 根接口：`http://localhost:8000/`
- 健康检查：`http://localhost:8000/health`
- Swagger：`http://localhost:8000/docs`
- Milvus 健康检查：`http://localhost:9091/healthz`
- MinIO 控制台：`http://localhost:9001`

本地 API 和 Worker 分别使用 `Ctrl+C` 停止。停止容器但保留数据：

```powershell
docker compose stop
```

不要随意执行 `docker compose down -v`，其中 `-v` 会删除 MySQL、Milvus、etcd
和 MinIO 的命名 Volume。

默认开发管理员：

```text
用户名：admin
密码：admin123
```

该账号仅用于本地开发，部署前必须修改默认密码和 `JWT_SECRET_KEY`。

## 12. 当前限制与下一步

- 数据库现由 Alembic 管理，部署必须先执行 `alembic upgrade head`。
- Worker 已独立部署，可通过副本数及 `DOCUMENT_WORKER_CONCURRENCY` 扩容。
- 知识库生命周期使用 Saga/Outbox，文档切片使用稳定 ID + upsert 保证幂等重试。
- 旧 Collection 仍可检索，但 auto-ID 主键无法原地改造；上传会被明确拒绝，需新建
  知识库并迁移文档后才能获得幂等入库和 Sparse 索引。
- 上游 Embedding 账户额度耗尽时，上传和启用 RAG 的检索会返回 502。
