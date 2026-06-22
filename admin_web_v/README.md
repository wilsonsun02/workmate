
## 项目定位

| 目录 | 说明 |
| `admin_web_v/` | 基于 Vben Admin 官方 Monorepo 重构的新管理端，UI 基座为 Element Plus |

当前仅保留 `apps/web-ele` 作为实际业务应用。

---

## 环境要求

| 工具 | 版本要求 |
|------|----------|
| Node.js | 建议 `22.x` |
| pnpm | 使用仓库声明版本，首次安装前建议启用 Corepack |

如果当前 Node 版本较低，可执行：

```bash
nvm use 22
```

启用 Corepack（首次）：

```bash
npm i -g corepack
```

---

## 安装与启动

在 `admin_web_v/` 根目录执行：

```bash
pnpm install
pnpm dev:ele
```

默认开发入口为 `apps/web-ele`，启动后访问本地开发服务器。

---

## 开发代理

`apps/web-ele/vite.config.ts` 已将以下前缀代理到本地管理后端：

```
/api/admin  →  http://127.0.0.1:8010
```

联调时请先启动后端管理服务：

```bash
python admin_serve.py
```

---

## 构建命令

在 `admin_web_v/` 根目录执行：

```bash
# 类型检查
pnpm -F @vben/web-ele run typecheck

# 生产构建
pnpm build:ele
```

构建产物位于 `apps/web-ele/dist/`。

---

## 运行时配置

线上保留 `apps/web-ele/public/runtime-config.js`，API 地址按以下优先级读取：

1. `window.__APP_CONFIG__.VITE_ADMIN_API_BASE`
2. `.env` 中的 `VITE_GLOB_API_URL`
3. 默认回退 `/api/admin`

生产环境可通过替换 `runtime-config.js` 覆盖接口地址，**无需重新打包**。

---

## 许可证

[MIT © Vben-2020](./LICENSE)
