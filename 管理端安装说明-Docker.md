# Workmate 管理端安装说明（Docker 方式）

## 1. 文档说明

本文档用于指导在 Docker 环境下部署并验证 Workmate 管理端。\
管理端运行依赖以下两个服务：

- `admin`：管理端后端接口服务（默认端口 `8010`）
- `admin-web`：管理端前端页面服务（默认端口 `8080`，构建入口为 `admin_web_v/apps/web-ele`）

镜像瘦身说明：

- `admin` 使用 `requirements.admin.txt`，只安装管理端接口所需依赖
- `admin` 镜像只复制 `admin_serve.py`、`admin_api/` 与少量 `workflow` 配置代码
- `Dockerfile.admin.dockerignore` 会把管理端构建上下文限制在必要文件内
- 本地数据库、checkpoint、workspace、output、logs 不会打入镜像；管理端通过 `.env` 中的 `WORKMATE_DB_*` 连接外部数据库
- `skills/` 通过 `docker-compose.admin.yml` 挂载到 `/app/skills`，不再烘进后端镜像
- `admin-web` 使用 `admin_web_v/apps/web-ele/Dockerfile` 构建静态前端，最终运行镜像为 nginx

## 2. 前置条件

请确认以下条件已满足：

- 已安装 Docker Engine 与 Docker Compose（建议 Compose v2）
- 已获取项目源码，并可进入项目根目录：`<REPO_ROOT>`
- 项目根目录已准备 `.env` 配置文件（可从 `.env.admin.example` 复制）

环境校验命令：

```bash
docker --version
docker compose version
```

## 3. 统一配置

所有 Docker 部署参数统一写在项目根目录 `.env` 中：

```bash
cp .env.admin.example .env
```

常用配置项：

| 分类 | 参数 |
|---|---|
| 镜像与容器 | `WORKMATE_ADMIN_IMAGE`、`WORKMATE_ADMIN_WEB_IMAGE`、`WORKMATE_ADMIN_CONTAINER_NAME`、`WORKMATE_ADMIN_WEB_CONTAINER_NAME` |
| 端口与 API | `WORKMATE_ADMIN_PORT_HOST`、`WORKMATE_ADMIN_PORT`、`WORKMATE_ADMIN_WEB_PORT_HOST`、`VITE_ADMIN_API_BASE` |
| 数据库 | `WORKMATE_DB_HOST`、`WORKMATE_DB_DATABASE`、`WORKMATE_DB_USER`、`WORKMATE_DB_PASS` |
| 挂载路径 | `WORKMATE_SKILLS_DIR`、`WORKMATE_MCP_OPERABLE_DIRS_CONFIG` |
| Redis | `REDIS_HOST`、`REDIS_PORT`、`REDIS_PASSWORD` |
| OSS | `OSS_ENDPOINT`、`OSS_REGION`、`OSS_BUCKET`、`OSS_ACCESS_KEY_ID`、`OSS_ACCESS_KEY_SECRET`、`OSS_AUTH_MODE`、`OSS_STS_TOKEN` |
| 技能分发 | `SKILL_INSTALL_TRIGGER_MODE`、`SKILL_AUTO_UPGRADE_MAX_CONCURRENCY`、`SKILL_AUTO_UPGRADE_RETRY_TIMES`、`SKILL_AUTO_UPGRADE_RETRY_BACKOFF_SEC`、`SKILL_ROLLOUT_DEFAULT_BATCH_SIZE`、`SKILL_ROLLOUT_FAILURE_THRESHOLD` |
| MCP 开关 | `MCP_ENABLE_WINDOWS_TOOLS`、`MCP_ENABLE_COMMON_TOOLS`、`MCP_ENABLE_DOCUMENT_TOOLS`、`MCP_ENABLE_EXECUTION_TOOLS`、`MCP_ENABLE_MEDIA_TOOLS`、`MCP_ENABLE_SEARCH_TOOLS`、`MCP_ENABLE_WECHAT_TOOLS`、`MCP_ENABLE_HAPP_TOOLS` |

## 4. 部署步骤

### 4.1 进入项目目录

```bash
cd <REPO_ROOT>
```

### 4.2 构建并启动服务

#### 4.2.1 启动 `admin` 和 `admin-web`

```bash
docker compose -f docker-compose.admin.yml up -d --build
```

说明：

- 该模式只启动管理端后端接口和前端页面
- 本地 `./skills` 会挂载到容器 `/app/skills`，用于技能浏览、编辑、上传和打包
- `admin-web` 通过 `.env` 中的 `VITE_ADMIN_API_BASE` 访问 `admin` 的 `/api/admin`
- 如遇依赖下载超时，可在 `.env` 中设置 `PIP_INDEX_URL`

`--build` 表示构建或更新本地镜像，`-d` 表示后台运行容器。

### 4.3 检查服务状态

```bash
docker compose -f docker-compose.admin.yml ps
```

预期结果：

- `admin`、`admin-web` 两个服务处于 `Up` 状态

### 4.4 查看服务日志（可选）

如需排查问题，可执行：

```bash
docker compose -f docker-compose.admin.yml logs -f admin
docker compose -f docker-compose.admin.yml logs -f admin-web
```

## 5. 验收步骤

### 5.1 管理端服务端健康检查

```bash
curl http://127.0.0.1:8010/admin/health
```

预期结果：返回内容包含 `status: ok`。

### 5.2 管理端 API 验证

调用任一 `/api/admin/*` 接口，确认服务端返回正常。

### 5.3 管理端前端访问验证

浏览器访问：

- `http://127.0.0.1:8080`

预期结果：页面可正常打开并显示登录或管理界面。

## 6. 运维常用命令

### 6.1 停止服务

```bash
docker compose -f docker-compose.admin.yml down
```

### 6.2 启动服务

```bash
docker compose -f docker-compose.admin.yml up -d
```

### 6.3 升级部署（同机重建）

```bash
cd <REPO_ROOT>
docker compose -f docker-compose.admin.yml down
docker compose -f docker-compose.admin.yml up -d --build
docker compose -f docker-compose.admin.yml ps
```

## 7. 常见问题与处理建议

### 7.1 `docker compose up` 执行失败

- 先执行 `docker compose -f docker-compose.admin.yml config` 校验编排文件语法
- 再确认 Docker 守护进程已启动且可用

### 7.2 端口冲突（`8010` 或 `8080`）

- 修改 `.env` 中的 `WORKMATE_ADMIN_PORT_HOST` 或 `WORKMATE_ADMIN_WEB_PORT_HOST` 后重启
- 或释放冲突端口

### 7.3 接口请求失败

- 先看服务状态：`docker compose -f docker-compose.admin.yml ps`
- 再看后端日志：`docker compose -f docker-compose.admin.yml logs --tail 200 admin`
- 如页面可访问但接口失败，再看前端运行配置：`docker compose -f docker-compose.admin.yml logs --tail 200 admin-web`

### 7.4 macOS 环境 Colima 启动失败

- 常见原因是网络无法下载基础镜像
- 建议切换可访问网络后重试 `colima start`
