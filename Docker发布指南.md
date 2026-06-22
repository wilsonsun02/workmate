# Workmate Docker 发布指南（中文）

本文档面向当前仓库的 `docker-compose.admin.yml`，覆盖管理端两包镜像的构建、标签、推送、回滚、常见故障排查、最小验收清单与执行结果记录模板。

## 1. 当前 Compose 对应关系

`<REPO_ROOT>/docker-compose.admin.yml` 当前定义了 2 个服务：

| 服务名 | 镜像（当前） | 端口映射 | 关键环境变量 | 依赖关系 |
|---|---|---|---|---|
| `admin` | `workmate-admin:local`（由根目录 `Dockerfile.admin` 构建） | `8010:8010` | `WORKMATE_ADMIN_HOST=0.0.0.0`、`WORKMATE_ADMIN_PORT=8010`、`BASE_DIR=/app` | 无 |
| `admin-web` | `workmate-admin-web:local`（由 `admin_web_v/apps/web-ele/Dockerfile` 构建） | `8080:80` | `VITE_ADMIN_API_BASE=http://localhost:8010/api/admin` | 依赖 `admin` |

说明：
- 管理端后端使用独立 `Dockerfile.admin`，容器内只启动 `admin_serve.py`。
- `Dockerfile.admin` 使用 `requirements.admin.txt`，不安装非管理端所需的 LLM、文档处理、视频处理、调度器或 Windows 自动化依赖。
- `Dockerfile.admin.dockerignore` 会把管理端构建上下文限制在必要文件内。
- 本地数据库、checkpoint、workspace、output、logs 不写入镜像；管理端通过 `.env` 中的 `WORKMATE_DB_*` 连接外部数据库。
- `Dockerfile.admin` 只复制管理端后端代码与少量运行配置；`skills/` 由 compose 挂载，不写入镜像层。
- 管理端前端由 `admin_web_v/apps/web-ele/Dockerfile` 构建，最终以 nginx 提供静态页面。

## 2. 发布前准备

- 本地具备 Docker / Docker Compose（建议 Compose v2）。
- 根目录存在 `.env` 并包含生产可用配置（可从 `.env.admin.example` 复制）。
- 已登录镜像仓库（示例：`docker login`）。
- 明确版本号（示例：`v0.2.0`）与发布环境（测试/生产）。

`.env` 是 Docker 部署的统一配置入口，至少确认以下参数：

```bash
WORKMATE_DB_HOST=
WORKMATE_DB_DATABASE=
WORKMATE_DB_USER=
WORKMATE_DB_PASS=
WORKMATE_ADMIN_PORT_HOST=8010
WORKMATE_ADMIN_WEB_PORT_HOST=8080
VITE_ADMIN_API_BASE=http://localhost:8010/api/admin
```

发布打标签时可在 shell 中临时设置：

```bash
export REGISTRY=registry.example.com
export NAMESPACE=workmate
export VERSION=v0.2.0
```

## 3. 构建步骤（Build）

### 3.1 一次性构建 compose 内所有服务镜像

```bash
cd <REPO_ROOT>
docker compose -f docker-compose.admin.yml build --pull
```

### 3.2 产物检查

```bash
docker images | grep -E "workmate-admin|workmate-admin-web"
```

预期至少存在：
- `workmate-admin:local`
- `workmate-admin-web:local`

## 4. 标签步骤（Tag）

将本地 `local` 标签打为仓库版本标签：

```bash
docker tag workmate-admin:local ${REGISTRY}/${NAMESPACE}/workmate-admin:${VERSION}
docker tag workmate-admin-web:local ${REGISTRY}/${NAMESPACE}/workmate-admin-web:${VERSION}
```

可选：同步打 `latest`（仅在流程允许时）

```bash
docker tag workmate-admin:local ${REGISTRY}/${NAMESPACE}/workmate-admin:latest
docker tag workmate-admin-web:local ${REGISTRY}/${NAMESPACE}/workmate-admin-web:latest
```

## 5. 推送步骤（Push）

```bash
docker push ${REGISTRY}/${NAMESPACE}/workmate-admin:${VERSION}
docker push ${REGISTRY}/${NAMESPACE}/workmate-admin-web:${VERSION}
```

如使用 `latest`：

```bash
docker push ${REGISTRY}/${NAMESPACE}/workmate-admin:latest
docker push ${REGISTRY}/${NAMESPACE}/workmate-admin-web:latest
```

## 6. 部署与回滚步骤

### 6.1 部署新版本（推荐：显式指定镜像标签）

方式 A（推荐）：在部署机使用覆盖文件固定镜像版本（不改主 compose）：

```yaml
# docker-compose.release.yml
services:
  admin:
    image: registry.example.com/workmate/workmate-admin:v0.2.0
    build: null
  admin-web:
    image: registry.example.com/workmate/workmate-admin-web:v0.2.0
    build: null
```

部署命令：

```bash
docker compose -f docker-compose.admin.yml -f docker-compose.release.yml pull
docker compose -f docker-compose.admin.yml -f docker-compose.release.yml up -d
docker compose -f docker-compose.admin.yml -f docker-compose.release.yml ps
```

方式 B：直接改 `docker-compose.admin.yml` 的 `image` 标签到发布版本并去掉 `build`，再执行：

```bash
docker compose -f docker-compose.admin.yml pull
docker compose -f docker-compose.admin.yml up -d
```

### 6.2 回滚步骤（按上一稳定版本）

1. 确认上一稳定版本号（示例：`v0.1.9`）。
2. 将部署使用的镜像标签切回 `v0.1.9`（覆盖文件或 compose 主文件）。
3. 执行：

```bash
docker compose -f docker-compose.admin.yml -f docker-compose.release.yml pull
docker compose -f docker-compose.admin.yml -f docker-compose.release.yml up -d
docker compose -f docker-compose.admin.yml -f docker-compose.release.yml ps
```

4. 验证健康状态与关键接口（见“最小验收清单”）。

建议保留最近 2~3 个稳定版本标签，避免回滚时找不到镜像。

## 7. 常见故障排查

### 7.1 管理端容器启动失败

排查：
- 查看容器日志：
  - `docker logs workmate-admin --tail 200`
- 查看容器状态：
  - `docker inspect --format='{{json .State}}' workmate-admin`

关注点：
- 管理端健康检查访问 `http://127.0.0.1:8010/admin/health`
- 端口、启动命令、`.env` 配置是否被覆盖错误

### 7.2 构建失败（依赖安装异常）

排查：
- 后端：`requirements.admin.txt` 中依赖是否可安装。
- 前端：`admin_web_v/pnpm-lock.yaml` 与 `admin_web_v/package.json` 是否匹配（pnpm 冻结安装）。
- 网络代理/镜像源是否可访问。

### 7.3 推送失败（鉴权/权限）

排查：
- `docker login` 是否针对正确 registry。
- 命名空间是否有 push 权限。
- 标签命名是否符合仓库策略（是否允许 `latest`）。

## 8. 最小验收清单（上线后）

- [ ] `docker compose -f docker-compose.admin.yml ps` 显示 `admin`、`admin-web` 均为 `Up`。
- [ ] `curl http://<部署机IP>:8010/admin/health` 返回成功。
- [ ] 浏览器访问 `http://<部署机IP>:8080` 可打开管理前端。
- [ ] 管理端前端可成功请求 `/api/admin/*`（至少 1 个接口通过）。
- [ ] 容器日志无持续报错（近 10 分钟）。

## 9. 执行结果记录模板（发布/回滚通用）

可复制以下模板到发布工单或变更系统：

```text
【变更类型】发布 / 回滚
【项目】Workmate
【执行人】
【执行时间】
【环境】测试 / 生产

【版本信息】
- 目标版本：vX.Y.Z
- 回滚来源版本（如有）：vA.B.C
- 管理端后端镜像：<registry>/<namespace>/workmate-admin:<tag>
- 管理端前端镜像：<registry>/<namespace>/workmate-admin-web:<tag>

【执行命令】
1) docker compose -f docker-compose.admin.yml build --pull
2) docker tag ...
3) docker push ...
4) docker compose -f docker-compose.admin.yml -f docker-compose.release.yml pull
5) docker compose -f docker-compose.admin.yml -f docker-compose.release.yml up -d

【结果记录】
- 容器状态（ps）：通过 / 不通过
- admin 健康检查：通过 / 不通过
- admin-web 页面访问：通过 / 不通过

【异常与处理】
- 异常描述：
- 定位过程：
- 处理动作：
- 是否触发回滚：是 / 否

【最终结论】
- 本次变更：成功 / 失败
- 后续跟踪事项：
```

---

如需后续将版本标签改为自动化（例如 Git Commit SHA + GitHub Actions/GitLab CI 自动推送），可在此文档基础上扩展 CI/CD 发布流水线章节。

## 10. 本机执行记录（2026-05-11）

执行环境：macOS（当前开发机）

### 10.1 Docker/Compose 安装与版本校验

已执行：

```bash
brew install docker docker-compose docker-buildx colima
docker --version
docker compose version
docker buildx version
```

结果：通过（CLI 工具可用）。

### 10.2 Compose 配置校验

已执行：

```bash
docker compose -f docker-compose.admin.yml config
```

结果：通过（编排文件语法可解析）。

### 10.3 阻塞项（导致无法完成容器实跑）

已执行：

```bash
COLIMA_HOME=<REPO_ROOT>/.colima colima start --cpu 2 --memory 4 --disk 20 --verbose
```

结果：失败，网络超时（访问 GitHub 镜像地址失败），未能启动 Docker 守护进程。

影响：
- 无法完成 `docker compose -f docker-compose.admin.yml build/up` 实跑验收；
- 无法完成 `admin/admin-web` 健康检查与前后端联通实测。

建议：
- 在可访问 GitHub 资源的网络环境重试 `colima start`；
- 或直接使用已安装 Docker Desktop/企业内网镜像源的验收机执行第 8 节最小验收清单。
