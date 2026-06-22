# WorkMate `admin_web_v` 说明

## 项目定位

- `admin_web_v/` 是基于 Vben Admin 官方 Monorepo 重构的新管理端。
- 当前仅保留 `apps/web-ele` 作为实际业务应用，UI 基座为 Element Plus。

## 环境要求

- Node.js：建议使用 `22.x`
- pnpm：使用仓库声明版本，首次安装前建议启用 Corepack

如果当前 Node 版本较低，可执行：

```bash
nvm use 22
```

## 安装与启动

在 `admin_web_v/` 根目录执行：

```bash
pnpm install
pnpm dev:ele
```

默认开发入口为 `apps/web-ele`。

## 开发代理

`apps/web-ele/vite.config.ts` 已将以下前缀代理到本地管理后端：

```text
/api/admin -> http://127.0.0.1:8010
```

联调时请先启动后端管理服务，例如：

```bash
python admin_serve.py
```

## 构建命令

在 `admin_web_v/` 根目录执行：

```bash
pnpm -F @vben/web-ele run typecheck
pnpm build:ele
```

构建产物位于 `apps/web-ele/dist/`。

## 运行时配置

- 线上继续保留 `apps/web-ele/public/runtime-config.js`
- API 地址优先读取：
  - `window.__APP_CONFIG__.VITE_ADMIN_API_BASE`
  - `.env` 中的 `VITE_GLOB_API_URL`
  - 默认回退 `/api/admin`

这意味着生产环境可以通过替换 `runtime-config.js` 覆盖接口地址，而无需重新打包。

## 登录态兼容

为了兼容旧管理端，当前登录态沿用以下本地存储键：

- `workmate_admin_token`
- `workmate_admin_user`

相关适配位置：

- `apps/web-ele/src/api/request.ts`
- `apps/web-ele/src/api/core/auth.ts`
- `apps/web-ele/src/api/core/user.ts`
- `apps/web-ele/src/store/auth.ts`

## 已迁移页面

- 登录
- 控制塔总览
- 通用设置
- Prompt 配置
- 员工管理
- 中期记忆维护
- 在线用户
- 登录凭证
- MCP 服务器管理
- Skills 技能
- 成本与资源管理
- 安全与合规审计

## 当前实现说明

- 页面样式已切到 Vben Admin + Element Plus 体系。
- 业务页以旧逻辑复用为主，优先保证接口兼容和迁移速度。
- `src/styles/workmate.css` 用于给迁移页面补统一业务样式壳层。

## 当前技术债

- 部分迁移页面暂时保留 `// @ts-nocheck`，用于先跑通旧页面逻辑。
- 后续若继续演进，建议按页面逐步拆分：
  - API 模块
  - composables
  - 业务组件
- 当前权限模式为前端静态路由模式，未接入后端动态菜单。

## 维护约束

- 如涉及数据库表结构调整，仍需补独立 SQL migration 脚本。
