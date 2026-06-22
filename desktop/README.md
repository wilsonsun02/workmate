# Desktop · PyQt 内嵌网页壳

使用 PyQt6 `QWebEngineView` 加载 **`desktop/ui/`** 下的本地单页界面（登录、主界面、设置弹窗），样式参考 QClaw 类桌面助手。依赖通过 `pyproject.toml` 的 **`dependency-groups.desktop`** 管理，与主项目服务依赖隔离。

**与 Admin 对接（登录、WebSocket、技能配置与安装）**：见仓库根目录 [`docs/admin-desktop-integration.md`](../docs/admin-desktop-integration.md)。

## 环境准备

在项目根目录执行（首次会下载 Qt / WebEngine，体积较大）：

```bash
uv sync --group desktop
```

## 运行

在项目根目录：

```bash
uv run --group desktop python -m desktop.webview_shell
```

若当前解释器已安装 `desktop` 组依赖，也可：

```bash
python -m desktop.webview_shell
```

默认打开 **`desktop/ui/index.html`**，并通过查询参数注入 API 基址（供登录请求使用）。关闭主窗口时会弹出 **退出确认**（是/否）。

### 错误日志

桌面版会将运行日志写入 `logs/` 目录：

- 打包运行时：默认可写时使用安装目录（与 `WorkmateDesktop.exe` 同级）下的 `logs/`、`config/`、`workspace/`；若安装目录不可写（例如安装在 `Program Files`），则回退到 `%LOCALAPPDATA%/WorkmateDesktop/`。`desktop.log` 默认仅记录 `ERROR` 级别
- 开发运行时：默认在当前工作目录的 `desktop_temp/logs/`
- 可在 `config/desktop_config.json` 中设置 `logs_dir` 为绝对路径，修改桌面壳日志目录（修改后需重启生效）

主要日志文件：

- `desktop.log`：桌面壳未捕获异常、启动/退出、后端拉起状态
- `serve.log`：后端运行日志（含 MCP 启动自检结果）
- `workmate.log`：其他入口的通用运行日志（由 `sitecustomize.py` 兜底初始化）

打包运行时，`desktop.log`、`serve.log`、`workmate.log` 默认仅记录 `ERROR` 级别；开发运行时仍保留 `INFO` 级别。

可选：将后端日志同时输出到终端（便于开发时观察 MCP/DeepAgent 初始化）

- 在 `.env` 中设置 `WORKMATE_LOG_STDOUT=1`（支持 `true/yes/on`）
- 重启后端后生效；日志仍会持续写入 `serve.log`
- 无控制台打包（`console=False`）时 `sys.stdout` 不可用，该选项会被自动忽略，仅写日志文件

### MCP 启动自检

桌面端启动后会触发后端依赖自检：检查当前启用的 `stdio` MCP 所需命令（如 `npx`、`uvx`、`uv`）是否可用。

- 自检结果会写入 `serve.log`（例如 `MCP stdio dependency check passed/failed ...`）
- 若存在缺失依赖，桌面端会弹出告警，并在 `desktop.log` 记录摘要
- 可通过 `GET /api/desktop/mcp_runtime_check` 查看当前自检结果（供桌面壳读取）；`check` 内含 `missing_count` / `stdio_count`（与 `missing_commands` / `stdio_servers` 长度一致，便于客户端直接展示）

### 账号密码登录

登录请求发往：`{admin_api_base}/api/admin/auth/login`（由独立 [admin_serve.py](../admin_serve.py) 提供）。请先在本机启动后端与管理端，例如：

```bash
uv run python serve.py
uv run python admin_serve.py
```

管理员账号需已在 `sys_admin_users` 等表中可用（见 `admin_api` 用户校验逻辑）。若无法连接服务，界面会提示检查 `api_base` 与网络。

### 对话与流式接口

主界面输入框在**回车**（不含 Shift）或点击发送时，会按 [main.py](../main.py) 中 `run_stream_quotation` 相同约定请求 **`POST {api_base}/quotation`**：`mode: 0`、`thread_id` / `sessionId`（按会话生成并持久化在本地，格式同 `generate_session_id`）、`username` 取已登录用户或默认 `Workmate`。服务端需已运行 `serve.py` 以返回 SSE；流结束后以 `event_type === "done"` 的 `content` 作为助手消息展示。**Shift+Enter** 仍可在输入框内换行。

助手消息使用 **Markdown** 渲染（GFM、换行），依赖页面中的 jsDelivr CDN 脚本 `marked` + `DOMPurify`；无网络时需将对应 UMD 文件放到 `desktop/ui/vendor/` 并改 `index.html` 引用。

### 环境变量与远程页

| 变量 | 说明 |
|------|------|
| `WORKMATE_API_BASE` | Agent API 根地址，默认 `http://127.0.0.1:8009`，会写入 `index.html?api_base=...` |
| `WORKMATE_ADMIN_API_BASE` | Admin API 根地址，默认 `http://127.0.0.1:8010`，会写入 `index.html?admin_api_base=...` |

### 桌面配置文件

桌面端支持配置文件（可扩展更多选项）：

- 默认模板：`desktop/config/desktop_config.json`
- 运行时覆盖：`config/desktop_config.json`（位于运行目录，首次启动自动生成）

当前内置配置项：

- `api_base`: Agent 后端 API 基址（若设置环境变量 `WORKMATE_API_BASE`，环境变量优先）
- `admin_api_base`: Admin 后端 API 基址（若设置环境变量 `WORKMATE_ADMIN_API_BASE`，环境变量优先）
- `workspace_root`: 当前使用者的工作区根目录；留空时自动为「与桌面 exe 同级」的 `workspace/`
- `output_base_dir`: Agent 产出根目录；留空时自动为「与 exe 同级」的 `workspace/`（后端写入 `{output_base_dir}/{业务用户名}/{日期}/`）
- `output_dir_template`: 界面展示的「默认输出路径」模板，默认 `{output_base_dir}/{username}`
- `auto_create_workspace_root`: 保存配置时自动创建 `workspace_root` 目录（默认 `true`）
- `backend_auto_start`: 是否自动拉起本地后端
- `backend_health_timeout_seconds`: 后端健康检查超时（预留）
- `desktop_global_log_level`: 可选。桌面端全局日志级别，仅支持 `DEBUG` / `INFO` / `ERROR`；留空时开发态默认 `INFO`、打包态默认 `ERROR`。该项会影响桌面壳进程日志（`desktop.log`）以及桌面壳自动拉起的后端日志（`serve.log`/`workmate.log`）。
- `logs_dir`: 可选。非空时为绝对路径，桌面日志写入该目录
- `webengine_storage_root`: 可选。留空时默认使用 `workspace_root/webengine/`（修改后需重启桌面端生效）
- `wechat_attachment_save_dir` / `wechat_attachment_cache_file` / `wechat_audio_cache_file`: 可选。留空时默认分别在 `workspace_root/{username}/wechat/attachments`、`workspace_root/{username}/wechat/config/` 下。打包并由桌面壳拉起 `serve.exe` 时会注入对应 `WECHAT_*` 环境变量（见 [mcp_filesystem/tools/wechat.py](../mcp_filesystem/tools/wechat.py)）。

**输出目录与后端对齐**：桌面壳拉起本机 `serve.exe` 时，将解析后的 `output_base_dir`（默认与 exe 平级的 `workspace/`）作为 `OUTPUT_BASE_DIR` 传给后端（与 [workflow/config.py](../workflow/config.py) 一致），Agent 实际写入 `{OUTPUT_BASE_DIR}/{业务用户名}/{日期}/`。开发态（未打包）下，若 `backend_auto_start` 为 `true` 且本机 API 尚未就绪，壳会用当前解释器自动启动仓库根目录的 `serve.py`，并同样注入 `OUTPUT_BASE_DIR`（默认可到 `desktop_temp/workspace`）。若你已在另一终端手动启动了 `serve.py` 且未在 `.env` 中设置 `OUTPUT_BASE_DIR`，健康检查会认为后端已就绪而不会二次拉起，此时后端可能仍写入 `{BASE_DIR}/workspace`；需与桌面 `desktop_temp/workspace` 对齐时，请在 `.env` 中设置 `OUTPUT_BASE_DIR` 或先停止手动进程、仅由桌面自启 `serve`。

登录后，设置面板会显示解析后的“默认输出目录”，例如：`.../workspace/<username>`（取决于当前登录账号与模板）。
设置面板支持编辑 `workspace_root` 与 `output_dir_template`，点击“本地保存”会直接写回运行目录的 `config/desktop_config.json` 并立即生效；点击“恢复默认”会重置并写回默认配置。可在同一 JSON 中手动维护上述可选路径字段；设置表单仅负责工作区三项，保存时会保留其它键不丢失。

### 个人计算机部署时单独维护的文件

分发到个人机时，建议在installation目录（`workmate-desktop.exe` 与 `serve.exe` 所在文件夹）长期维护：

| 文件 / 目录 | 说明 |
|-------------|------|
| `.env` | 与 `serve.exe` 同级（见 [serve.spec](../serve.spec)）：API Key、`REPORT_DB_*`、`BASE_DIR`（若安装根非 exe 所在目录则需显式设）、`MCP_READ_ALLOWED_DIRS`、以及可选的 `OUTPUT_BASE_DIR`（手动启动后端时与工作区对齐）、微信缓存路径环境变量等 |
| `config/desktop_config.json` | 与桌面 `exe` 同级下的 `config/`，或开发时由壳首次写入；含 API 地址、工作区、日志/WebEngine/微信路径等 |
| `config/mcp_servers.json` 等 | 随安装包拷贝后按机器情况修改 |
| `skills/`、`prompt/`、`template/`、`checkpoints/` | 按需携带，与后端 `BASE_DIR` 约定一致；登录 Admin 后，桌面会根据 WebSocket 下发的 `skill_market` 与待安装任务自动下载 ZIP 并解压到安装根下 `skills/<名称>/`（与 [cloud_client.py](../cloud_client.py) 行为对齐），并回写 `config/skills_config.json` |

**微信附件与音频缓存**（不设则相对 `BASE_DIR` 下默认路径）：可在 `.env` 或桌面 JSON 中指定（桌面拉起后端时以 JSON 注入为准）：`WECHAT_ATTACHMENT_SAVE_DIR`、`WECHAT_ATTACHMENT_CACHE_FILE`、`WECHAT_AUDIO_CACHE_FILE`，推荐使用绝对路径以便系统清理或与安装目录分离。

仍可通过**第一个命令行参数**指定任意 **http(s) URL**，此时不加载本地 UI，行为与旧版一致：

```bash
uv run --group desktop python -m desktop.webview_shell https://example.com/
```

## 打包为 exe（PyInstaller）

项目 `dev` 依赖组已包含 `pyinstaller`。**必须把 `desktop/ui` 整目录一并带上**，否则默认入口找不到本地页面。

若希望桌面端启动时自动拉起后端 `serve.py`，需要把后端先打成 `serve.exe` 并和桌面端一起分发（见下方 `serve.spec` + 目录结构）。

**onedir 示例**（将 `ui` 放在生成 exe 同目录下）：

```bash
uv sync --group desktop --group dev
uv run --group desktop --group dev pyinstaller --noconfirm --windowed --name workmate-desktop ^
  --collect-all PyQt6 --collect-all PyQt6-WebEngine ^
  --add-data "desktop/ui;ui" ^
  desktop/webview_shell.py
```

（Linux/macOS 将 `;` 改为 `:`。）

生成后请确认 `dist/workmate-desktop/ui/index.html` 存在；若使用 **onefile**，需把 `ui` 打进 `_MEIPASS`（同样用 `--add-data "desktop/ui;ui"`），壳内会按 `_MEIPASS/ui` 与 `exe 同目录/ui` 顺序查找。

单文件、图标、额外隐藏导入等可按部署环境在命令中增减。

### 更换桌面端 Logo / 图标

桌面端有三处“品牌图标”来源：

1. **页面 Logo（登录页 + 左侧栏）**
   - 默认文件：`desktop/ui/assets/logo.ico`
   - 前端使用该文件渲染，不需要改代码即可替换（保持文件名一致最简单）。

2. **运行时窗口图标（任务栏/窗口左上角）**
   - 启动时会按顺序尝试加载：
     - 打包目录：`assets/app.ico`
     - 打包目录：`ui/assets/app.ico`
     - 打包目录：`ui/assets/logo.ico`
     - 打包目录：`ui/assets/logo.svg`
     - 开发目录：`desktop/assets/app.ico`
     - 开发目录：`desktop/ui/assets/app.ico`
     - 开发目录：`desktop/ui/assets/logo.ico`
     - 开发目录：`desktop/ui/assets/logo.svg`
   - 建议提供 `app.ico` 以获得最稳定的 Windows 展示效果。

3. **exe 文件图标（资源管理器图标）**
   - PyInstaller spec 会在 `desktop/assets/app.ico` 存在时自动注入 `icon` 参数；
   - 若文件不存在，则跳过图标参数，打包不会失败。

### 打包时一并启动后端（推荐）

最简单方式：使用一条命令自动完成“后端 + 桌面 + 归并”：

```bash
uv run --group desktop --group dev python -m desktop.build_bundle
```

该命令会执行 `pyinstaller -y workmate-bundle.spec`，在单个目录内同时产出：
- `workmate-desktop.exe`
- `serve.exe`
- 一份共享的 `_internal/`（避免两套依赖重复）

同时会自动清洗 `dist/workmate-desktop/config/desktop_config.json`（以及 `_internal/config/desktop_config.json`）中的运行时路径字段，避免把开发机绝对路径打进安装包。

目录示例：

```text
dist/
  workmate-desktop/
    workmate-desktop.exe
    serve.exe
    _internal/
    ui/
      index.html
      ...
```

若你想手动分步，也可按以下方式：

1. 先打后端：

```bash
uv run --group dev pyinstaller -y serve.spec
```

2. 再打桌面壳：

```bash
uv run --group desktop --group dev pyinstaller -y workmate-desktop.spec
```

3. 将 `dist/serve/` 复制到 `dist/workmate-desktop/serve/`（此方案会有双份 `_internal`，体积更大）。

3. 发布目录建议如下（关键是 `serve/serve.exe` 在桌面 exe 同级）：

```text
dist/
  workmate-desktop/
    workmate-desktop.exe
    ui/
      index.html
      ...
    serve/
      serve.exe
      ...后端依赖文件
```

`workmate-desktop.exe` 启动后会在以下条件满足时自动拉起后端：
- 当前是打包运行（frozen）
- `WORKMATE_API_BASE` 指向本机（默认 `http://127.0.0.1:8009`）
- 目标端口未检测到已有服务

如果 `WORKMATE_API_BASE` 指向远程服务，则不会尝试启动本地后端。

## 入口与前端文件

| 路径 | 说明 |
|------|------|
| [webview_shell.py](webview_shell.py) | 主窗口、WebEngine 权限（本地页访问远程 API、`localStorage`）；默认持久化在 `workspace_root/webengine/`，或由 `webengine_storage_root` 覆盖 |
| [ui/index.html](ui/index.html) | 页面骨架 |
| [ui/styles.css](ui/styles.css) | 样式入口（聚合各 CSS 子模块） |
| [ui/css/base.css](ui/css/base.css) | 变量、基础样式、启动遮罩与登录区样式 |
| [ui/css/layout.css](ui/css/layout.css) | 主体布局与侧边栏样式 |
| [ui/css/chat.css](ui/css/chat.css) | 消息区、Markdown 与输入框样式 |
| [ui/css/modal.css](ui/css/modal.css) | 设置弹窗与确认弹窗样式 |
| [ui/app.js](ui/app.js) | 前端模块入口（负责绑定页面事件与启动流程） |
| [ui/js/layout.js](ui/js/layout.js) | 页面结构模板渲染（将主布局从 index.html 抽离） |
| [ui/js/markdown.js](ui/js/markdown.js) | Markdown 渲染与安全清洗 |
| [ui/js/ids.js](ui/js/ids.js) | ID/会话标识相关工具函数 |
| [ui/js/storage.js](ui/js/storage.js) | 会话、偏好、对话列表本地存储逻辑 |
| [ui/js/sse.js](ui/js/sse.js) | `/quotation` 流式 SSE 解析 |
| [ui/js/chat.js](ui/js/chat.js) | 对话列表、消息渲染、发送与流式回复 |
| [ui/js/auth.js](ui/js/auth.js) | 登录/登出与用户信息 UI 同步 |
| [ui/js/settings.js](ui/js/settings.js) | 设置弹窗与偏好开关绑定 |
