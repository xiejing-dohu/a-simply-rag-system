# 智能 RAG 系统后端架构说明

本目录是 FastAPI 后端，负责认证与权限、用户隔离、模型发现、SSE 流式聊天、
Token 配额、文档处理、Embedding、Milvus 检索以及 MySQL 知识库元信息管理。
Python 依赖和虚拟环境统一由 `uv` 管理。

## 1. 架构概览

```text
Vue 前端
  │ REST / SSE
  ▼
FastAPI（app/main.py）
  ├─ 认证、角色、会话归属、Token 配额
  ├─ OpenAI-compatible /models 与 /chat/completions
  ├─ knowledge_repository.py ── SQLAlchemy async ── MySQL
  ├─ knowledge_runtime.py ───── 文档解析 / Embedding ── Milvus
  └─ rag/retriever.py ───────── Dense / MMR / BM25 + RRF
                                                    │
Milvus ── etcd（内部元数据）+ MinIO（对象数据）
```

当前是“混合持久化”的开发版本：

| 数据 | 存储位置 | 重启后 |
| --- | --- | --- |
| 用户、登录 Token、失败次数 | FastAPI 进程内存 | 清空并恢复默认管理员 |
| 会话、消息、消息 RAG 上下文 | FastAPI 进程内存 | 清空 |
| Token 累计和 5 小时/周窗口 | FastAPI 进程内存 | 清空 |
| 知识库、Collection 映射 | MySQL `knowledge_bases` | 保留 |
| 文档处理元信息 | MySQL `knowledge_documents` | 保留 |
| 切片文本、字段、向量 | Milvus | 保留 |
| Milvus 内部元数据和对象 | etcd / MinIO | Docker Volume 保留 |

这条边界很重要：当前不能把内存用户和 MySQL 中 `created_by`、Milvus 中
`uploaded_by` 当作完整的生产级外键关系。生产化时应将用户、认证、会话、消息和
配额一起迁移到 MySQL，并使用密码哈希和正式 JWT。

## 2. 目录与模块职责

```text
Backend/
├── .env                         # 本地运行配置，不提交密钥
├── pyproject.toml               # uv 项目及依赖声明
├── uv.lock                      # 可复现依赖锁
├── docker-compose.yml           # MySQL、etcd、MinIO、Milvus
├── README.md
└── app/
    ├── main.py                  # 当前实际入口和全部 FastAPI 路由
    ├── knowledge_repository.py  # MySQL 知识库/文档仓储和序列化
    ├── knowledge_runtime.py     # 解析、Token 切片、Embedding、Milvus CRUD
    ├── db/
    │   ├── mysql.py             # SQLAlchemy 异步引擎和 Session
    │   └── milvus.py            # Milvus 基础连接模块
    ├── models/
    │   ├── knowledge_base.py    # 当前启用的知识库 ORM 模型
    │   ├── knowledge_document.py# 当前启用的文档 ORM 模型
    │   ├── user.py
    │   ├── conversation.py
    │   └── message.py           # 后三者为后续持久化准备，当前入口未使用
    ├── rag/
    │   └── retriever.py         # 实际 RAG 检索、预算裁剪、Prompt 格式化
    ├── api/                     # 分层路由骨架，当前请求仍由 main.py 承接
    ├── core/                    # 配置、安全、依赖模块
    ├── schemas/                 # 分层 Pydantic Schema 骨架
    └── services/                # 分层业务服务骨架
```

当前运行入口为 `app.main:app`。`api/`、`schemas/` 和 `services/` 中存在早期或
预留的分层文件，但新增功能应以 `main.py` 的实际路由和本文为准，后续可逐步将
入口中的内存业务拆入这些层。

## 3. 启动生命周期

FastAPI `lifespan` 在启动时执行 `init_knowledge_tables()`，仅创建当前知识库
运行时拥有的两张表：

- `knowledge_bases`
- `knowledge_documents`

服务停止时释放 SQLAlchemy Engine 连接池。Milvus Collection 不在启动时全量
重建；知识库通过 MySQL 中的 `collection_name` 恢复与已有 Collection 的映射。

## 4. 认证、权限与隔离

### 认证

- 登录接口生成随机 Bearer Token，并在内存中建立 Token 到用户 ID 的映射。
- 连续 3 次密码错误后按用户名锁定 5 分钟，响应携带 `Retry-After`。
- 登录成功后清除该用户名的失败记录。
- 停用用户返回 HTTP 403。

当前密码为开发版明文内存数据，不适合生产环境。

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

## 7. 文档处理和入库架构

支持 `.docx`、`.xlsx`、`.xls`、`.csv`、`.txt`、`.md` 和 `.pdf`，单文件最大
30 MB。旧版 `.doc` 不受支持，需要先转换为 `.docx`。

入库流水线：

```text
管理员上传 multipart 文件
  → 校验知识库、大小、扩展名、切片参数
  → 提取文本
  → Excel 拼接全部工作表、字段和数据行
  → tiktoken 按 chunk_tokens / overlap_tokens 切片
  → 调用 EMBEDDING_MODEL 生成知识库指定维度向量
  → 写入对应 Milvus Collection
  → MySQL 写入文档元信息
  → 更新知识库 file_count / chunk_count
```

切片参数：

- `chunk_tokens`：64–8192；
- `overlap_tokens`：0–4096，且必须小于 `chunk_tokens`。

DashScope `text-embedding-v4` 当前配置支持 64、128、256、512、768、1024、
1536、2048 维。后端通过 `/knowledge-bases/embedding-config` 将实际模型、
服务商、可选维度和扩展名返回给前端。

Milvus Collection 主要字段：

| 字段 | 说明 |
| --- | --- |
| `id` | 自动生成主键 |
| `text` | 切片原文 |
| `document_name` | 来源文件 |
| `source_type` | 来源扩展名 |
| `chunk_index` | 文件内切片序号 |
| `token_count` | 切片 Token 数 |
| `uploaded_by` | 上传用户 ID |
| `created_at` | 写入时间 |
| `embedding` | 固定维度向量 |

### 跨存储一致性

创建知识库时先创建 Milvus Collection，再写 MySQL；若后续失败，后端尝试删除
刚创建的 Collection。上传文档时先写 Milvus，再写 MySQL；如果 MySQL 提交失败，
后端根据本次返回的主键删除已写入向量。

这是补偿式一致性，不是 MySQL 与 Milvus 的分布式事务。进程在两个操作之间被
强制终止时仍可能产生孤立数据，生产环境需要任务表、幂等键和定期对账机制。

## 8. RAG 检索架构

`app/rag/retriever.py` 提供三种模式：

| 模式 | 实现 | 适用场景 |
| --- | --- | --- |
| `semantic` | Dense 候选 + MMR 重排 | 需要语义相关且减少重复切片 |
| `dense` | Milvus COSINE 直接排名 | 单纯按向量相似度检索 |
| `hybrid` | Dense + 本地 BM25，经 RRF 融合 | 同时重视语义和精确关键词 |

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

`docker-compose.yml` 只负责数据库相关服务，前后端仍在本机直接运行：

| 服务 | 镜像/版本 | 本机端口 | 用途 |
| --- | --- | --- | --- |
| MySQL | `mysql:8.0` | 3306 | 业务元信息 |
| Milvus | `milvusdb/milvus:v2.4.23` | 19530、9091 | 向量和切片 |
| etcd | `quay.io/coreos/etcd:v3.5.5` | 容器网络 | Milvus 元数据 |
| MinIO | `minio/minio` | 9000、9001 | Milvus 对象存储 |

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
| `OPENAI_API_KEY` | 模型服务密钥 | 必填 |
| `OPENAI_API_BASE` | OpenAI-compatible `/v1` 根地址 | 必填 |
| `DEFAULT_MODEL` | 默认聊天模型 | 必填 |
| `EMBEDDING_MODEL` | 向量模型 | 必填 |
| `AVAILABLE_MODELS` | 可选聊天模型允许列表 | 可选 |
| `MODEL_PROVIDER` | 前端展示的服务商名称 | 可选 |

`.env` 中还保留 JWT 相关配置键，但当前开发入口使用随机内存 Token，尚未接入
正式 JWT。

## 11. 启动、检查与停止

先启动数据服务：

```powershell
cd D:\智能rag系统\Backend
docker compose up -d
docker compose ps
```

再使用 uv 安装依赖并启动后端：

```powershell
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

检查地址：

- 根接口：`http://localhost:8000/`
- 健康检查：`http://localhost:8000/health`
- Swagger：`http://localhost:8000/docs`
- Milvus 健康检查：`http://localhost:9091/healthz`
- MinIO 控制台：`http://localhost:9001`

停止后端使用 `Ctrl+C`。停止数据容器但保留数据：

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

该账号仅用于本地开发，部署前必须替换认证实现与默认凭据。

## 12. 当前限制与下一步

- 用户、认证、会话、消息和 Token 配额尚未持久化。
- 密码尚未哈希，Bearer Token 不是 JWT。
- 跨 MySQL/Milvus 只提供应用层补偿，不是原子事务。
- BM25 候选在应用侧计算，超大知识库需要改为可扩展的稀疏索引方案。
- 上游 Embedding 账户额度耗尽时，上传和启用 RAG 的检索会返回 502。
- 下一阶段应优先完成用户/会话/配额 MySQL 迁移、数据库迁移工具、后台任务队列、
  幂等入库与集成测试。
