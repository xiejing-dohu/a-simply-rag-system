# 智能 RAG 系统前端说明

本目录是系统的 Web 客户端，使用 Vue 3、TypeScript、Vite、Pinia 和 Element Plus。
前端只负责交互、状态管理和结果展示；模型地址、API Key、可用聊天模型以及
Embedding 配置均由后端管理，浏览器不会直接连接模型服务或数据库。

## 1. 启动与配置

```powershell
cd D:\智能rag系统\Frontend
npm install
npm run dev
```

默认访问地址为 `http://localhost:5173`，默认后端地址为
`http://localhost:8000`。如需修改后端地址，在本目录创建 `.env.local`：

```env
VITE_API_BASE_URL=http://localhost:8000
```

常用命令：

| 命令 | 用途 |
| --- | --- |
| `npm run dev` | 启动 Vite 开发服务器 |
| `npm run build` | 执行 TypeScript 检查并生成生产构建 |
| `npm run preview` | 本地预览生产构建 |

## 2. 前端目录与调用关系

```text
src/
├── api/
│   ├── request.ts       # Axios 实例、API 根地址、Bearer Token、401 处理
│   ├── auth.ts          # 登录、注册、用户、Token 配额
│   ├── chat.ts          # 会话、RAG 设置、SSE 流式聊天
│   ├── knowledge.ts     # 知识库、上传、Milvus 数据浏览
│   └── model.ts         # 聊天模型发现
├── components/
│   ├── AppLayout.vue
│   ├── ChatMessage.vue
│   ├── ModelSelector.vue
│   └── TokenUsagePopover.vue
├── router/index.ts      # 页面路由和权限守卫
├── stores/
│   ├── auth.ts
│   ├── chat.ts
│   └── knowledge.ts
├── types/index.ts       # 接口响应的 TypeScript 类型
└── views/
    ├── LoginView.vue
    ├── ChatView.vue
    ├── KnowledgeView.vue
    └── AdminView.vue
```

普通请求的调用链为：

```text
Vue View/Component → Pinia Store → src/api → Axios → FastAPI
```

流式聊天的调用链为：

```text
ChatView → chat Store → fetch/ReadableStream → SSE 事件 → 增量更新消息
```

## 3. 接口通用约定

- API 根地址：`VITE_API_BASE_URL`，未设置时为 `http://localhost:8000`。
- 除注册、登录、根路由、健康检查和模型发现外，业务接口均要求登录。
- 登录成功后保存 Access JWT 和 Refresh Token；Access 过期时自动刷新并重试一次。
- Axios 请求拦截器自动添加 `Authorization: Bearer <token>`。
- 非登录请求收到 HTTP 401 时，前端删除本地 Token 并跳转 `/login`。
- 普通接口响应为 JSON；参数校验错误采用 FastAPI 的 HTTP 422 格式。
- 时间字段是后端返回的 ISO 8601 字符串。

通用错误响应：

```json
{
  "detail": "可展示给用户的错误信息"
}
```

常见状态码：

| 状态码 | 含义 |
| --- | --- |
| 400 | 文件为空、格式不支持或文档处理失败 |
| 401 | 未登录、Token 无效或密码错误 |
| 403 | 账户停用或权限不足 |
| 404 | 用户、会话、知识库或 Milvus 集合不存在 |
| 409 | 用户名或邮箱已存在 |
| 413 | 上传文件超过 30 MB |
| 422 | 请求字段或业务参数校验失败 |
| 429 | 登录锁定或 Token 配额耗尽 |
| 502 | 上游 Embedding 服务调用失败 |
| 503 | MySQL、Milvus、RAG 或模型服务异常 |

### 系统状态接口

| 方法 | 路径 | 认证 | 说明 |
| --- | --- | --- | --- |
| GET | `/` | 否 | 返回服务状态、运行说明和 Swagger 路径 |
| GET | `/health` | 否 | 返回 `status` 以及当前三类数据的存储模式 |

`/health` 是轻量存活与架构状态接口，目前不会逐项探测 MySQL 和 Milvus 的实际
连通性。需要确认依赖服务时应结合 `docker compose ps` 和 Milvus `/healthz`。

## 4. 用户与认证接口

### 4.1 登录

`POST /auth/token`

请求类型为 `multipart/form-data`：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `username` | string | 是 | 用户名 |
| `password` | string | 是 | 密码 |

成功响应：

```json
{
  "access_token": "server-generated-token",
  "refresh_token": "server-generated-refresh-token",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {
    "id": 1,
    "username": "admin",
    "email": "admin@example.com",
    "role": "admin",
    "is_root_admin": true,
    "is_active": true,
    "created_at": "2026-07-30T00:00:00+00:00",
    "five_hour_token_limit": null,
    "weekly_token_limit": null,
    "five_hour_tokens_used": 0,
    "weekly_tokens_used": 0,
    "input_tokens_used": 0,
    "output_tokens_used": 0,
    "total_tokens_used": 0,
    "five_hour_window_started_at": "2026-07-30T00:00:00+00:00",
    "weekly_window_started_at": "2026-07-30T00:00:00+00:00",
    "five_hour_resets_at": "2026-07-30T05:00:00+00:00",
    "weekly_resets_at": "2026-08-06T00:00:00+00:00"
  }
}
```

密码错误返回 401 和 `密码错误`，前端保留已输入内容。连续 3 次密码错误后返回
429、`Retry-After: 300`，该用户名 5 分钟内不可登录。

### 4.2 注册

`POST /auth/register`

```json
{
  "username": "demo",
  "email": "demo@example.com",
  "password": "123456"
}
```

约束：用户名 2–50 字符，密码至少 6 字符，邮箱必须符合基本邮箱格式。注册后的
身份固定为 `employee`。响应为 `User` 对象，不会返回密码。

### 4.3 当前用户与用户管理

| 方法 | 路径 | 权限 | 请求/响应 |
| --- | --- | --- | --- |
| GET | `/auth/me` | 登录用户 | 返回当前 `User` 及用量 |
| POST | `/auth/refresh` | Refresh Token | 换取新的 Access JWT |
| POST | `/auth/logout` | 无 | 吊销 Redis 中的 Refresh Token |
| GET | `/auth/users` | 管理员 | 返回 `User[]` |
| PUT | `/auth/users/{user_id}` | 管理员 | 更新状态、身份或限额，返回 `User` |
| POST | `/auth/users/{user_id}/token-usage/reset` | 管理员 | 重置用量窗口，返回 `User` |

更新用户示例：

```json
{
  "role": "employee",
  "is_active": true,
  "five_hour_token_limit": 100000,
  "weekly_token_limit": null
}
```

限额必须为正整数，`null` 表示无限。系统管理员 `is_root_admin=true` 不可降级或
停用；只有系统管理员可以修改身份。由普通用户提升的管理员可以管理状态和配额，
但不能修改任何用户身份，也不能修改系统管理员账户。

重置窗口请求：

```json
{
  "scope": "five_hour"
}
```

`scope` 可为 `five_hour`、`weekly` 或 `all`。重置窗口不会清除累计输入、输出和
总 Token。

## 5. 模型接口

`GET /models/`

可选查询参数 `refresh=true` 用于跳过 5 分钟缓存并重新探测上游 `/models`。

响应：

```json
[
  {
    "id": "qwen-plus-latest",
    "name": "qwen-plus-latest",
    "description": "从 /models 自动发现",
    "provider": "DashScope"
  }
]
```

前端不硬编码聊天模型：启动后读取该接口，并优先自动选择后端 `.env` 所配置的
默认模型。API Key 永远只保存在后端。

## 6. 会话与聊天接口

### 6.1 会话接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/chat/conversations` | 获取当前用户的会话，按更新时间倒序 |
| POST | `/chat/conversations` | 新建会话 |
| DELETE | `/chat/conversations/{conversation_id}` | 删除自己的会话和消息 |
| GET | `/chat/conversations/{conversation_id}/messages` | 获取自己的会话消息 |
| PUT | `/chat/conversations/{conversation_id}/model` | 修改会话模型 |
| PUT | `/chat/conversations/{conversation_id}/rag` | 保存会话 RAG 设置 |

新建会话请求：

```json
{
  "title": "新对话",
  "model_name": "qwen-plus-latest",
  "rag_enabled": true,
  "knowledge_base_id": 1,
  "retrieval_mode": "hybrid",
  "max_retrieval_tokens": 2048
}
```

`retrieval_mode` 支持：

- `semantic`：Dense 候选加 MMR 重排；
- `dense`：Milvus COSINE 相似度直接排序；
- `hybrid`：Dense 与 BM25 排名经 RRF 融合。

`max_retrieval_tokens` 范围为 128–16000。启用 RAG 时
`knowledge_base_id` 必填且必须存在。

会话响应：

```json
{
  "id": 1,
  "title": "新对话",
  "model_name": "qwen-plus-latest",
  "knowledge_base_id": 1,
  "rag_enabled": true,
  "retrieval_mode": "hybrid",
  "max_retrieval_tokens": 2048,
  "created_at": "2026-07-30T00:00:00+00:00",
  "updated_at": "2026-07-30T00:00:00+00:00"
}
```

切换模型：

```json
{
  "model_name": "qwen-max-latest"
}
```

保存 RAG 设置：

```json
{
  "rag_enabled": true,
  "knowledge_base_id": 1,
  "retrieval_mode": "semantic",
  "max_retrieval_tokens": 4096
}
```

消息响应中的助手消息可包含 `rag_context`，因此刷新会话后仍可重新展示本轮引用
的知识切片。

### 6.2 SSE 流式聊天

`POST /chat/conversations/{conversation_id}/messages/stream`

请求为 JSON，并携带 Bearer Token：

```json
{
  "content": "请总结知识库中的部署方式",
  "rag_enabled": true,
  "knowledge_base_id": 1,
  "retrieval_mode": "hybrid",
  "max_retrieval_tokens": 2048
}
```

响应类型为 `text/event-stream`。事件之间用空行分隔，顺序如下：

1. 启用 RAG 时先发送一次 `rag` 事件；
2. 发送零个或多个默认 `message` 事件；
3. 上游或生成错误时发送 `error` 事件；
4. 最后发送 `[DONE]`。

RAG 事件示例：

```text
event: rag
data: {"enabled":true,"knowledge_base_id":1,"mode":"hybrid","retrieved_tokens":486,"sources":[{"id":9,"text":"切片原文","document_name":"部署说明.docx","source_type":"docx","chunk_index":2,"token_count":486,"score":0.91,"created_at":"2026-07-30T00:00:00+00:00","truncated":false}]}

```

文本增量事件：

```text
data: {"content":"根据"}

data: {"content":"知识库资料，"}

```

错误与结束事件：

```text
event: error
data: {"message":"模型调用失败"}

data: [DONE]

```

前端 `src/api/chat.ts` 使用 `fetch` 和 `ReadableStream` 手动解析 SSE，这是因为
原生 `EventSource` 只支持 GET，不能满足本接口的 POST JSON 请求。`onRag` 保存
召回上下文，`onChunk` 将文本片段追加到正在生成的助手消息。若连接结束前没有
收到 `[DONE]`，前端提示“模型流意外中断”。

## 7. 知识库与 Milvus 接口

### 7.1 Embedding 配置

`GET /knowledge-bases/embedding-config`

```json
{
  "model": "text-embedding-v4",
  "provider": "DashScope",
  "supported_dimensions": [64, 128, 256, 512, 768, 1024, 1536, 2048],
  "default_dimension": 1024,
  "supported_extensions": [".csv", ".docx", ".md", ".pdf", ".txt", ".xls", ".xlsx"]
}
```

前端使用该响应生成文件选择限制和向量维度选项，不自行维护 Embedding 模型配置。

### 7.2 知识库

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/knowledge-bases/` | 登录用户 | 获取知识库列表 |
| POST | `/knowledge-bases/` | 管理员 | 创建 MySQL 记录和 Milvus Collection |
| DELETE | `/knowledge-bases/{knowledge_base_id}` | 管理员 | 删除 Collection 和知识库记录 |

创建请求：

```json
{
  "name": "产品文档",
  "description": "内部产品和部署资料",
  "vector_dimension": 1024
}
```

向量维度必须属于 Embedding 配置返回的 `supported_dimensions`，Collection 创建
后维度固定。

知识库响应：

```json
{
  "id": 1,
  "name": "产品文档",
  "description": "内部产品和部署资料",
  "collection_name": "kb_generated_uuid",
  "embedding_model": "text-embedding-v4",
  "vector_dimension": 1024,
  "file_count": 1,
  "chunk_count": 12,
  "created_by": 1,
  "created_at": "2026-07-30T00:00:00"
}
```

### 7.3 文档上传和文档列表

`POST /knowledge-bases/{knowledge_base_id}/documents/`

管理员使用 `multipart/form-data` 上传。接口写完临时文件并创建任务后立即返回
HTTP 202，前端随后轮询任务进度：

| 字段 | 类型 | 范围 | 说明 |
| --- | --- | --- | --- |
| `file` | File | 最大 30 MB | 待处理文件 |
| `chunk_tokens` | integer | 64–8192 | 单切片最大 Token |
| `overlap_tokens` | integer | 0–4096 | 相邻切片重叠量，必须小于切片大小 |

支持 `.docx`、`.xlsx`、`.xls`、`.pdf`、`.txt`、`.md` 和 `.csv`。Excel 在后端
先按工作表、列名和数据行拼接为完整文本，再统一切片。

排队响应：

```json
{
  "status": "queued",
  "task": {
    "id": "task-uuid",
    "knowledge_base_id": 1,
    "file_name": "手册.xlsx",
    "file_size": 10240,
    "chunk_tokens": 512,
    "overlap_tokens": 64,
    "status": "queued",
    "stage": "queued",
    "progress": 0,
    "result_document_id": null,
    "error": null
  }
}
```

`GET /knowledge-bases/tasks/{task_id}` 返回实时状态。阶段依次为 `queued`、
`parsing`、`splitting`、`embedding`、`milvus`、`metadata`、`completed`；
失败时为 `failed` 并包含 `error`。

`GET /knowledge-bases/{knowledge_base_id}/documents/` 返回该知识库的
`KnowledgeDocument[]`。

### 7.4 Milvus 字段和切片

`GET /knowledge-bases/{knowledge_base_id}/milvus/schema`

返回 Collection 名称、描述、实体数量、字段定义和索引信息：

```json
{
  "collection_name": "kb_generated_uuid",
  "description": "Knowledge base chunks",
  "entity_count": 12,
  "fields": [
    {
      "name": "embedding",
      "type": "FLOAT_VECTOR",
      "is_primary": false,
      "auto_id": false,
      "dimension": 1024,
      "max_length": null
    }
  ],
  "indexes": []
}
```

`GET /knowledge-bases/{knowledge_base_id}/milvus/chunks?limit=50&cursor=123`

- `cursor`：上一页最后一条主键；首页不传；
- `offset`：仅用于兼容旧客户端，新页面使用游标；
- `limit`：1–200，默认 50。

响应：

```json
{
  "items": [
    {
      "id": 9,
      "text": "处理后的切片原文",
      "document_name": "手册.xlsx",
      "source_type": "xlsx",
      "chunk_index": 0,
      "token_count": 487,
      "uploaded_by": 1,
      "created_at": "2026-07-30T00:00:00+00:00"
    }
  ],
  "offset": 0,
  "limit": 50,
  "total": 12,
  "next_cursor": 456
}
```

## 8. 页面权限和状态说明

- 登录页提供登录和普通用户注册。
- 聊天页对所有已登录用户开放，会话由后端按用户 ID 隔离。
- 知识库读取对已登录用户开放，创建、删除和上传只允许管理员。
- 管理页由路由守卫限制为管理员访问，最终权限仍以后端校验为准。
- 顶部 Token 面板显示当前用户累计用量、5 小时/周窗口、管理员设置的具体上限或
  “无限”模式。
- 用户、会话、消息、Token 用量和任务状态均保存在 MySQL；刷新令牌和登录锁定
  保存在 Redis，后端重启不会清空业务数据。
