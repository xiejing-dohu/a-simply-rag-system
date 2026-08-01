# agent-

智能 RAG 系统，包含 Vue 3 前端、FastAPI 后端、MySQL 知识库元信息存储以及
Milvus 向量检索。

项目架构、功能和启动方式请查看 [项目说明文件.md](项目说明文件.md)。

配置好 `Backend/.env` 并启动 Docker Desktop 后，可在 PowerShell 中一键启动数据
服务、数据库迁移、后端 API、独立 Worker 和前端：

```powershell
.\start.ps1
```

如果系统阻止执行本地脚本，只对当前 PowerShell 窗口临时放行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\start.ps1
```

默认按 `Ctrl+C` 只停止前后端应用，Docker 数据服务继续运行；需要同时停止数据
容器时使用 `.\start.ps1 -StopDataOnExit`，数据卷不会被删除。

也可以在 Git Bash、WSL 或 Linux 中运行 Shell 版本：

```bash
chmod +x start.sh
./start.sh
```

Shell 版本停止数据容器的参数为 `./start.sh --stop-data`。

- 前端接口说明：[Frontend/README.md](Frontend/README.md)
- 后端架构说明：[Backend/README.md](Backend/README.md)
