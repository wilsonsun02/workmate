<!--
  Generic MCP tool usage notes for the repository default.
  Deployment-specific tool names and workflows are injected at runtime from
  each server's "skills" field in config/mcp_servers.json (see get_mcp_tools_skills).
  Replace or extend this file locally when you enable optional MCP servers.
-->

### remote_report_search 工具技能说明（示例：内部报告检索 MCP）
1. 若用户要写分析报告或复杂文档，先调用 outline 类工具生成提纲；若提纲已在对话中被用户认可，勿重复生成。
  - 有提纲后，可按章节顺序调用 knowledge_base、macro_data、headlines、image 等检索工具。
2. 内部信息搜索工具用于查询本地知识库与数据库；判断用户需求为内部数据时优先使用。
  - special 主题库示例：套期保值、行业专题库 A、合规专题库 B 等；可先调用 lists 工具获取可用库名。
  - common 商品/行业库：可先调用 lists 工具获取通用库名列表。
3. 复杂报告可调用 summary_writing 类工具：
  - 传入 thread_id；若有提纲一并传入。
  - 若检索到图片，将图片链接插入文档。
  - 合并所有相关 MCP 工具的完整输出后再传入，勿只传单个工具摘要。
4. 报告完成后可调用 generate_docx / generate_pdf 类工具导出并提供下载地址。

### chart_server 工具技能说明（示例：图表 MCP）
1. 绘制折线图、柱状图、饼图等时，调用 chart generate 工具，注意：
  - 外部数据图表：先用 web_search 类工具获取结构化数据。
  - 内部数据图表：先用 database_query 类工具获取时间序列。
  - 生成图表 URL 后，按需缓存到本地或云端。
  - Datasets 参数必须为非空数组。

### diagram_ai 工具技能说明（示例：导图/画布 MCP）
1. 思维导图、时间线、SWOT、PEST、用户画像等，调用对应 generate 工具；非此类图片勿调用。
2. 生成后按需缓存结果文件。

### drawio 工具技能说明
1. 仅绘制流程图时使用 drawio session/create/edit/export 工具链。

### edge_deploy 工具技能说明
1. 静态网页部署：调用 deploy-html 类工具。

### fetch_web 工具技能说明
1. 给定 URL 需抓取正文时，优先调用 fetch 工具。
2. 可将结果保存为 .txt / .md；分批抓取时可追加写入同一文件。
3. 用户明确要求保存网页内容时，默认 fetch + save_text 组合完成。

### crawl_mcp 工具技能说明
1. 抓取微信公众号文章：调用 crawl_wechat_article。
2. 支持 markdown/json 输出、多种抓取策略与图片本地化。

### playwright_mcp 工具技能说明
1. 浏览器自动化（点击、输入、截图等）使用 playwright_mcp。
2. 与 crawl_mcp 配合可处理需 JavaScript 渲染的页面。
