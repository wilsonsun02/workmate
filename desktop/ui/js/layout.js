function renderBoot() {
  return `
  <div id="boot-overlay" class="boot-overlay" aria-live="polite">
    <div class="boot-card">
      <div class="boot-stage">
        <span id="boot-stage-text" class="boot-stage-text">阶段 1/2</span>
        <span id="boot-stage-name" class="boot-stage-name">启动服务</span>
      </div>
      <div class="boot-progress" aria-hidden="true">
        <div id="boot-progress-fill" class="boot-progress-fill"></div>
      </div>
      <div class="boot-spinner" aria-hidden="true"></div>
      <h2 class="boot-title">服务正在初始化</h2>
      <p id="boot-message" class="boot-message">正在启动本地服务，请稍候…</p>
      <details class="boot-details">
        <summary>查看初始化详情</summary>
        <div id="boot-log" class="boot-log"></div>
      </details>
    </div>
  </div>
  `;
}

function renderLogin() {
  return `
  <div id="login-screen" class="login-screen hidden" aria-hidden="true">
    <div class="login-card">
      <button type="button" class="login-close icon-btn" id="login-close" aria-label="关闭">×</button>
      <div class="brand-block">
        <div class="brand-logo" aria-hidden="true">
          <img class="brand-logo-img" src="./assets/logo.ico" alt="" />
        </div>
        <h1 class="brand-name">Workmate</h1>
      </div>
      <form id="login-form" class="login-form">
        <label class="field-label">账号</label>
        <input type="text" id="login-user" class="input-round" name="username" autocomplete="username" required />
        <label class="field-label">密码</label>
        <input type="password" id="login-pass" class="input-round" name="password" autocomplete="current-password" required />
        <label class="terms-row">
          <input type="checkbox" id="login-terms" />
          <span>我已阅读并同意《服务协议》与《隐私保护协议》</span>
        </label>
        <p class="form-error" id="login-error" role="alert"></p>
        <button type="submit" class="btn-primary btn-block" id="login-submit">登录</button>
      </form>
    </div>
  </div>
  `;
}

function renderShell() {
  return `
  <div id="app-shell" class="app-shell">
    <aside class="sidebar">
      <div class="sidebar-top">
        <div class="sidebar-brand">
          <span class="brand-logo-sm" aria-hidden="true">
            <img class="brand-logo-sm-img" src="./assets/logo.ico" alt="" />
          </span>
          <span class="brand-text">Workmate</span>
          <button type="button" class="icon-btn ghost" id="btn-new-chat" title="新对话">＋</button>
        </div>
        <div class="search-bar" role="search">
          <label for="sidebar-conversation-search" class="visually-hidden">搜索对话</label>
          <span class="search-icon" aria-hidden="true">🔍</span>
          <input
            type="search"
            id="sidebar-conversation-search"
            class="search-input"
            placeholder="搜索对话标题…"
            autocomplete="off"
            spellcheck="false"
            aria-label="按标题筛选对话与定时任务记录"
            enterkeyhint="search"
          />
          <button
            type="button"
            class="search-clear icon-btn ghost hidden"
            id="sidebar-search-clear"
            aria-label="清除搜索"
          >×</button>
        </div>
      </div>
      <div class="sidebar-history">
        <div class="history-group">
          <div class="history-label" id="conv-history-label">
            <span class="history-label-text">对话列表</span>
            <span class="batch-controls-slot" id="conv-batch-slot"></span>
            <button type="button" class="batch-icon-btn" id="sidebar-batch-conv-btn" title="批量管理对话">✓</button>
          </div>
          <div id="conversation-list" class="conversation-list"></div>
        </div>
        <div class="history-group">
          <div class="history-label history-label-row" id="collab-history-label">
            <button
              type="button"
              id="collab-section-toggle"
              class="history-label-text-btn"
              aria-expanded="true"
              aria-controls="collab-chain-list"
              title="展开/收起协同空间"
            >协同空间<span
                class="collab-section-badge hidden"
                id="collab-section-unread-badge"
                aria-label="未读协同数"
              >0</span></button>
            <span class="batch-controls-slot" id="collab-batch-slot"></span>
            <button type="button" class="batch-icon-btn" id="sidebar-batch-collab-btn" title="批量管理协同">✓</button>
            <span id="collab-section-chevron" class="history-label-chevron rotated">▸</span>
          </div>
          <div id="collab-chain-list" class="conversation-list"></div>
        </div>
        <div class="history-group">
          <div class="history-label history-label-row" id="sched-history-label">
            <button
              type="button"
              id="scheduler-section-toggle"
              class="history-label-text-btn"
              aria-expanded="false"
              aria-controls="scheduler-conversation-list"
              title="展开/收起定时任务列表"
            >定时任务</button>
            <span class="batch-controls-slot" id="sched-batch-slot"></span>
            <button type="button" class="batch-icon-btn" id="sidebar-batch-sched-btn" title="批量管理定时任务记录">✓</button>
            <span id="scheduler-section-chevron" class="history-label-chevron">▸</span>
          </div>
          <div id="scheduler-conversation-list" class="conversation-list hidden"></div>
        </div>
      </div>
      <div class="sidebar-bottom">
        <div class="sidebar-nav-views" role="tablist" aria-label="主功能">
          <button type="button" class="nav-view-btn active" id="nav-view-chat" role="tab" aria-selected="true">对话</button>
          <button type="button" class="nav-view-btn" id="nav-view-tasks" role="tab" aria-selected="false">定时任务</button>
          <button type="button" class="nav-view-btn" id="nav-view-knowledge" role="tab" aria-selected="false">知识库</button>
        </div>
        <div class="sidebar-user">
          <div class="avatar" id="sidebar-avatar">?</div>
          <div class="sidebar-user-meta">
            <span class="sidebar-user-name" id="sidebar-username">未登录</span>
          </div>
          <button
            type="button"
            class="icon-btn ghost btn-settings"
            id="btn-settings"
            title="设置"
            aria-haspopup="dialog"
            aria-label="设置"
          >
            ⚙
            <span class="settings-risk-badge hidden" id="settings-risk-badge" aria-hidden="true">
              <span class="settings-risk-count" id="settings-risk-count">0</span>
            </span>
          </button>
        </div>
      </div>
    </aside>

    <div class="main-column">
      <header class="top-bar">
      </header>

      <div id="view-chat" class="main-view">
        <main class="chat-area">
          <div class="messages" id="messages"></div>
        </main>

        <footer class="composer">
          <div class="composer-inner">
            <div id="composer-skill-chips" class="composer-skill-chips hidden" aria-live="polite"></div>
            <div id="composer-mcp-chips" class="composer-mcp-chips hidden" aria-live="polite"></div>
            <textarea id="composer-input" class="composer-input" rows="3" placeholder="请输入任务描述"></textarea>
            <div id="composer-attachments" class="composer-attachments hidden" aria-live="polite"></div>
            <div id="composer-knowledge-chips" class="composer-knowledge-chips hidden" aria-live="polite"></div>
            <input
              type="file"
              id="composer-file-input"
              class="visually-hidden"
              multiple
              accept=".xlsx,.xls,.xlsb,.csv,.jpg,.jpeg,.png,.webp,.gif,.bmp,.doc,.docx,.ppt,.pptx,.pdf,.txt,.md,.mp4,.mov,.avi,.mkv,.webm,.mp3,.wav,.m4a,.aac,.ogg,.flac,image/*,video/*,audio/*,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.ms-powerpoint,application/vnd.openxmlformats-officedocument.presentationml.presentation"
            />
            <div class="composer-toolbar">
              <div class="pills">
                <button type="button" class="pill" id="btn-attach" title="添加附件">📎 附件</button>
                <button type="button" class="pill" id="btn-knowledge" title="知识库">知识库</button>
                <button type="button" class="pill" id="btn-skills">技能 ▾</button>
                <button type="button" class="pill" id="btn-mcp">MCP ▾</button>
              </div>
              <button type="button" class="send-btn" id="btn-send" title="发送">➤</button>
            </div>
          </div>
        </footer>
      </div>

      <div id="view-tasks" class="main-view hidden" aria-hidden="true">
        <div id="tasks-root" class="tasks-root"></div>
      </div>

      <div id="view-collab" class="main-view hidden" aria-hidden="true">
        <div id="collab-detail-root" class="collab-root"></div>
      </div>

      <div id="view-knowledge" class="main-view hidden" aria-hidden="true">
        <div id="knowledge-root" class="knowledge-root"></div>
      </div>
    </div>

    <aside class="right-panel" id="right-panel">
      <div class="right-panel-top">
        <div class="right-panel-brand">
          <span class="right-panel-title">联系人</span>
          <button type="button" class="icon-btn ghost" id="btn-toggle-right-panel" title="折叠面板">◂</button>
        </div>
        <div class="search-bar" role="search">
          <label for="contacts-search" class="visually-hidden">搜索联系人</label>
          <span class="search-icon" aria-hidden="true">🔍</span>
          <input
            type="search"
            id="contacts-search"
            class="search-input"
            placeholder="搜索姓名或部门…"
            autocomplete="off"
            spellcheck="false"
            aria-label="搜索联系人"
          />
          <button
            type="button"
            class="search-clear icon-btn ghost hidden"
            id="contacts-search-clear"
            aria-label="清除搜索"
          >×</button>
        </div>
      </div>
      <div class="right-panel-content" id="contacts-tree"></div>
    </aside>
  </div>
  `;
}

function renderSkillsPanel() {
  return `
  <div id="skills-modal" class="skills-popover hidden" role="dialog" aria-hidden="true" aria-labelledby="skills-title">
    <div class="skills-popover-header">
      <h2 id="skills-title" class="skills-popover-title">选择技能</h2>
      <button type="button" class="icon-btn ghost" id="skills-close" aria-label="关闭">×</button>
    </div>
    <div class="skills-popover-search-wrap">
      <input type="search" id="skills-search-input" class="skills-popover-search" placeholder="搜索技能" autocomplete="off" spellcheck="false" />
    </div>
    <div id="skills-list" class="skills-select-list"></div>
    <div class="skills-popover-footer">
      <div id="skills-save-hint" class="skills-save-hint">点击技能即可选择或取消。</div>
      <button type="button" id="skills-manage-link" class="skills-manage-link">技能管理</button>
    </div>
  </div>
  `;
}

function renderSkillsManagePanel() {
  return `
  <div id="skills-manage-modal" class="modal-overlay hidden" aria-hidden="true">
    <div class="modal skills-modal" role="dialog" aria-labelledby="skills-manage-title">
      <button type="button" class="modal-close icon-btn" id="skills-manage-close" aria-label="关闭">×</button>
      <div class="skills-header">
        <h2 id="skills-manage-title" class="skills-title">技能管理</h2>
        <div class="skills-subtitle">
          <span id="skills-manage-sync-state" class="sync-state sync-state-local">
            <span class="sync-dot" aria-hidden="true"></span>
            <span class="sync-text">仅本地</span>
          </span>
        </div>
      </div>
      <div id="skills-manage-list" class="skills-list"></div>
      <div class="skills-footer">
        <div id="skills-manage-save-hint" class="skills-save-hint">切换开关将自动保存。</div>
      </div>
    </div>
  </div>
  `;
}

function renderMcpPanel() {
  return `
  <div id="mcp-modal" class="mcp-tool-popover hidden" role="dialog" aria-hidden="true" aria-labelledby="mcp-tool-title">
    <div class="mcp-tool-popover-header">
      <h2 id="mcp-tool-title" class="mcp-tool-popover-title">🔧 MCP工具选择</h2>
      <button type="button" class="icon-btn ghost" id="mcp-close" aria-label="关闭">×</button>
    </div>
    <div class="mcp-tool-popover-search-wrap">
      <input type="search" id="mcp-tool-search-input" class="mcp-tool-popover-search" placeholder="搜索MCP工具…" autocomplete="off" spellcheck="false" />
    </div>
    <div id="mcp-tool-list" class="mcp-tool-select-list"></div>
    <div class="mcp-tool-popover-footer">
      <div id="mcp-tool-status-hint" class="mcp-tool-status-hint">请选择需要使用的MCP工具</div>
      <div class="mcp-tool-footer-buttons">
        <button type="button" class="btn-confirm-primary" id="mcp-tool-confirm">确认</button>
        <button type="button" class="btn-confirm-secondary" id="mcp-tool-cancel">取消</button>
      </div>
    </div>
  </div>
  `;
}

function renderSettings() {
  return `
  <div id="settings-modal" class="modal-overlay hidden" aria-hidden="true">
    <div class="modal settings-modal" role="dialog" aria-labelledby="settings-title">
      <button type="button" class="modal-close icon-btn" id="settings-close" aria-label="关闭">×</button>
      <h2 id="settings-title" class="visually-hidden">设置</h2>
      <div class="settings-layout settings-layout-with-nav">
        <nav class="settings-nav" id="settings-nav" role="tablist" aria-label="设置导航">
          <button type="button" class="settings-nav-item active" data-panel="profile" role="tab" aria-selected="true" aria-controls="panel-profile">
            <span class="nav-item-icon">👤</span>
            <span class="nav-item-text">身份信息</span>
          </button>
          <button type="button" class="settings-nav-item" data-panel="general" role="tab" aria-selected="false" aria-controls="panel-general">
            <span class="nav-item-icon">⚙</span>
            <span class="nav-item-text">通用设置</span>
          </button>
          <button type="button" class="settings-nav-item" data-panel="wechat" role="tab" aria-selected="false" aria-controls="panel-wechat">
            <span class="nav-item-icon">💬</span>
            <span class="nav-item-text">微信设置</span>
          </button>
          <button type="button" class="settings-nav-item" data-panel="wxwork" role="tab" aria-selected="false" aria-controls="panel-wxwork">
            <span class="nav-item-icon">🏢</span>
            <span class="nav-item-text">企微设置</span>
          </button>
          <button type="button" class="settings-nav-item" data-panel="mcp" role="tab" aria-selected="false" aria-controls="panel-mcp">
            <span class="nav-item-icon">🔗</span>
            <span class="nav-item-text">MCP设置</span>
          </button>
          <button type="button" class="settings-nav-item" data-panel="skills" role="tab" aria-selected="false" aria-controls="panel-skills">
            <span class="nav-item-icon">🧩</span>
            <span class="nav-item-text">技能设置</span>
          </button>
          <button type="button" class="settings-nav-item" data-panel="templates" role="tab" aria-selected="false" aria-controls="panel-templates">
            <span class="nav-item-icon">📄</span>
            <span class="nav-item-text">模板管理</span>
          </button>
          <button type="button" class="settings-nav-item" data-panel="pref" role="tab" aria-selected="false" aria-controls="panel-pref">
            <span class="nav-item-icon">📋</span>
            <span class="nav-item-text">员工偏好</span>
          </button>
        </nav>
        <div class="settings-panels">
          <section class="settings-panel" id="panel-profile" role="tabpanel" aria-labelledby="nav-profile">
            <h3 class="panel-title">身份信息</h3>
            <div class="card profile-card" id="mate-info-card">
              <div class="avatar lg" id="settings-avatar">?</div>
              <div class="profile-card-info">
                <div>
                  <div class="profile-name" id="settings-username">—</div>
                  <span class="profile-tag">已登录</span>
                </div>
                <div class="mate-info-grid">
                  <div class="mate-info-item">
                    <span class="mate-info-label">姓名</span>
                    <span class="mate-info-value" id="mate-name">—</span>
                  </div>
                  <div class="mate-info-item">
                    <span class="mate-info-label">公司</span>
                    <span class="mate-info-value" id="mate-company">—</span>
                  </div>
                  <div class="mate-info-item">
                    <span class="mate-info-label">部门</span>
                    <span class="mate-info-value" id="mate-department">—</span>
                  </div>
                  <div class="mate-info-item">
                    <span class="mate-info-label">职位</span>
                    <span class="mate-info-value" id="mate-title">—</span>
                  </div>
                </div>
              </div>
            </div>
            <div class="card toggle-card prompt-cards-section" id="prompt-cards-section">
              <div class="toggle-row prompt-toggle-row" data-prompt="rich">
                <div>
                  <div class="toggle-title">🏢 公司信息</div>
                  <div class="toggle-desc">prompt/rich.md — 点击展开查看详情</div>
                </div>
                <span class="prompt-card-toggle" id="prompt-toggle-rich">▼</span>
              </div>
              <div class="prompt-card-body hidden" id="prompt-body-rich">
                <div class="prompt-card-loading">加载中…</div>
              </div>
              <div class="toggle-row prompt-toggle-row" data-prompt="department">
                <div>
                  <div class="toggle-title">🏭 部门信息</div>
                  <div class="toggle-desc">prompt/department.md — 点击展开查看详情</div>
                </div>
                <span class="prompt-card-toggle" id="prompt-toggle-department">▼</span>
              </div>
              <div class="prompt-card-body hidden" id="prompt-body-department">
                <div class="prompt-card-loading">加载中…</div>
              </div>
              <div class="toggle-row prompt-toggle-row" data-prompt="identity">
                <div>
                  <div class="toggle-title">👤 个人信息</div>
                  <div class="toggle-desc">prompt/identity.md — 点击展开查看详情</div>
                </div>
                <span class="prompt-card-toggle" id="prompt-toggle-identity">▼</span>
              </div>
              <div class="prompt-card-body hidden" id="prompt-body-identity">
                <div class="prompt-card-loading">加载中…</div>
              </div>
            </div>
            <button type="button" class="btn-logout" id="btn-logout">退出登录</button>
          </section>
          <section class="settings-panel hidden" id="panel-general" role="tabpanel" aria-labelledby="nav-general">
            <h3 class="panel-title">通用设置</h3>
            <div class="card toggle-card">
              <div class="toggle-row">
                <div>
                  <div class="toggle-title">默认输出目录</div>
                  <div class="toggle-desc" id="pref-output-path">-</div>
                </div>
              </div>
              <div class="cfg-form">
                <label class="cfg-label" for="cfg-output-base-dir">输出路径</label>
                <input
                  type="text"
                  id="cfg-output-base-dir"
                  class="cfg-input"
                  placeholder="例如：C:/workmate/workspace"
                />
                <label class="cfg-checkbox-row">
                  <input type="checkbox" id="cfg-auto-create-root" />
                  <span>保存时自动创建 output_base_dir 目录（不存在则创建）</span>
                </label>
              </div>
            </div>
            <!-- 允许访问路径 -->
            <div class="card toggle-card" style="margin-top:12px" id="mcp-read-dirs-card">
              <div class="toggle-row">
                <div>
                  <div class="toggle-title">允许访问路径</div>
                  <div class="toggle-desc">配置 Workmate 可以读取的目录列表</div>
                </div>
              </div>
              <div class="cfg-form">
                <div class="dir-list" id="mcp-read-dirs-list">
                  <div class="toggle-desc">加载中…</div>
                </div>
                <div class="cfg-actions" style="justify-content:flex-start">
                  <button type="button" class="btn-confirm-secondary" id="cfg-add-dir-btn">新增路径</button>
                </div>
              </div>
            </div>
            <div class="card toggle-card">
              <div class="toggle-row">
                <div>
                  <div class="toggle-title">安全防护</div>
                  <div class="toggle-desc">实时 AI 安全与内容策略（占位，仅本地记忆开关状态）</div>
                </div>
                <label class="switch">
                  <input type="checkbox" id="pref-security" />
                  <span class="slider"><span class="slider-knob" aria-hidden="true"></span></span>
                </label>
              </div>
              <div class="toggle-row">
                <div>
                  <div class="toggle-title">休眠阻止</div>
                  <div class="toggle-desc">保持计算机活跃（占位，未接系统 API）</div>
                </div>
                <label class="switch">
                  <input type="checkbox" id="pref-sleep" />
                  <span class="slider"><span class="slider-knob" aria-hidden="true"></span></span>
                </label>
              </div>
              <div class="toggle-row">
                <div>
                  <div class="toggle-title">工具权限限制</div>
                  <div class="toggle-desc">限制工具执行级别（占位）</div>
                </div>
                <label class="switch">
                  <input type="checkbox" id="pref-tools" />
                  <span class="slider"><span class="slider-knob" aria-hidden="true"></span></span>
                </label>
              </div>
            </div>
            <!-- 模型与模板配置 -->
            <div class="card toggle-card" style="margin-top:12px">
              <div class="toggle-row">
                <div>
                  <div class="toggle-title">模型与模板</div>
                  <div class="toggle-desc">配置图片生成供应商、LLM 供应商及模板目录</div>
                </div>
              </div>
              <div class="toggle-row">
                <div>
                  <div class="toggle-title">图片生成供应商 <span class="provider-badge" id="cfg-image-provider-badge">gemini</span></div>
                  <div class="toggle-desc">向左 gemini，向右 wan</div>
                </div>
                <label class="switch">
                  <input type="checkbox" id="cfg-image-provider" />
                  <span class="slider"><span class="slider-knob" aria-hidden="true"></span></span>
                </label>
              </div>
              <div class="toggle-row">
                <div>
                  <div class="toggle-title">LLM 供应商 <span class="provider-badge" id="cfg-llm-provider-badge">deepseek</span></div>
                  <div class="toggle-desc">向左 deepseek，向右 dashscope</div>
                </div>
                <label class="switch">
                  <input type="checkbox" id="cfg-llm-provider" />
                  <span class="slider"><span class="slider-knob" aria-hidden="true"></span></span>
                </label>
              </div>
              <div class="cfg-form">
                <label class="cfg-label" for="cfg-template-dir">报告模板目录</label>
                <input
                  type="text"
                  id="cfg-template-dir"
                  class="cfg-input"
                  placeholder="template/report-template"
                />
                <label class="cfg-label" for="cfg-image-template-dir">图片模板目录</label>
                <input
                  type="text"
                  id="cfg-image-template-dir"
                  class="cfg-input"
                  placeholder="template/image-template"
                />
              </div>
            </div>
            <!-- 记忆与压缩配置 -->
            <div class="card toggle-card" style="margin-top:12px">
              <div class="toggle-row">
                <div>
                  <div class="toggle-title">对话压缩</div>
                  <div class="toggle-desc">超长对话自动压缩保留关键链路</div>
                </div>
                <label class="switch">
                  <input type="checkbox" id="cfg-memory-compress-enabled" />
                  <span class="slider"><span class="slider-knob" aria-hidden="true"></span></span>
                </label>
              </div>
              <div class="cfg-form">
                <label class="cfg-label" for="cfg-memory-compress-threshold">压缩阈值（字符数）</label>
                <input
                  type="number"
                  id="cfg-memory-compress-threshold"
                  class="cfg-input"
                  placeholder="3000"
                  min="500"
                />
              </div>
              <div class="toggle-row">
                <div>
                  <div class="toggle-title">主题搜索</div>
                  <div class="toggle-desc">启用记忆主题搜索功能</div>
                </div>
                <label class="switch">
                  <input type="checkbox" id="cfg-memory-enable-topic-search" />
                  <span class="slider"><span class="slider-knob" aria-hidden="true"></span></span>
                </label>
              </div>
              <div class="cfg-form">
                <label class="cfg-label" for="cfg-memory-search-candidate-limit">搜索候选数量上限</label>
                <input
                  type="number"
                  id="cfg-memory-search-candidate-limit"
                  class="cfg-input"
                  placeholder="50"
                  min="1"
                />
              </div>
            </div>
            <!-- 记忆参数配置 -->
            <div class="card toggle-card" style="margin-top:12px">
              <div class="toggle-row">
                <div>
                  <div class="toggle-title">记忆参数</div>
                  <div class="toggle-desc">短期/中期记忆及相关性参数配置</div>
                </div>
              </div>
              <div class="cfg-form">
                <label class="cfg-label" for="cfg-memory-short-term-tasks">短期记忆：保留最近任务数</label>
                <input
                  type="number"
                  id="cfg-memory-short-term-tasks"
                  class="cfg-input"
                  placeholder="5"
                  min="1"
                />
                <label class="cfg-label" for="cfg-memory-mid-term-tasks">中期记忆：最大摘要条数</label>
                <input
                  type="number"
                  id="cfg-memory-mid-term-tasks"
                  class="cfg-input"
                  placeholder="25"
                  min="1"
                />
                <label class="cfg-label" for="cfg-memory-relevant-tasks-limit">相关性任务数量上限</label>
                <input
                  type="number"
                  id="cfg-memory-relevant-tasks-limit"
                  class="cfg-input"
                  placeholder="2"
                  min="1"
                />
              </div>
            </div>
            <!-- 沙箱与子代理配置 -->
            <div class="card toggle-card" style="margin-top:12px">
              <div class="toggle-row">
                <div>
                  <div class="toggle-title">沙箱模式</div>
                  <div class="toggle-desc">启用代码沙箱执行环境</div>
                </div>
                <label class="switch">
                  <input type="checkbox" id="cfg-use-sandbox" />
                  <span class="slider"><span class="slider-knob" aria-hidden="true"></span></span>
                </label>
              </div>
              <div class="toggle-row">
                <div>
                  <div class="toggle-title">子代理（Subagent）</div>
                  <div class="toggle-desc">启用子代理功能，系统将根据 subagents.json 配置构建并使用子代理</div>
                </div>
                <label class="switch">
                  <input type="checkbox" id="cfg-enable-subagents" />
                  <span class="slider"><span class="slider-knob" aria-hidden="true"></span></span>
                </label>
              </div>
            </div>
          </section>
          <section class="settings-panel hidden" id="panel-wechat" role="tabpanel" aria-labelledby="nav-wechat">
            <h3 class="panel-title">微信设置</h3>
            <div class="card toggle-card">
              <div class="cfg-form">
                <label class="cfg-label" for="cfg-wechat-window-title">微信程序名</label>
                <input
                  type="text"
                  id="cfg-wechat-window-title"
                  class="cfg-input"
                  placeholder="微信"
                />
                <label class="cfg-label" for="cfg-wechat-process-name">微信进程名</label>
                <input
                  type="text"
                  id="cfg-wechat-process-name"
                  class="cfg-input"
                  placeholder="Weixin"
                />
                <label class="cfg-label" for="cfg-wechat-ai-reply-prefix">微信回复前置语</label>
                <input
                  type="text"
                  id="cfg-wechat-ai-reply-prefix"
                  class="cfg-input"
                  placeholder="现在是Workmate与您对话"
                />
              </div>
            </div>
            <!-- 微信附件与缓存配置 -->
            <div class="card toggle-card" style="margin-top:12px">
              <div class="toggle-row">
                <div>
                  <div class="toggle-title">附件与缓存</div>
                  <div class="toggle-desc">微信附件保存目录及缓存文件路径</div>
                </div>
              </div>
              <div class="cfg-form">
                <label class="cfg-label" for="cfg-wechat-attachment-save-dir">附件保存目录</label>
                <input
                  type="text"
                  id="cfg-wechat-attachment-save-dir"
                  class="cfg-input"
                  placeholder="tools/wechat_attachments"
                />
                <label class="cfg-label" for="cfg-wechat-attachment-cache-file">附件缓存文件</label>
                <input
                  type="text"
                  id="cfg-wechat-attachment-cache-file"
                  class="cfg-input"
                  placeholder="tools/config/wechat_attachment_cache.json"
                />
                <label class="cfg-label" for="cfg-wechat-audio-cache-file">语音缓存文件</label>
                <input
                  type="text"
                  id="cfg-wechat-audio-cache-file"
                  class="cfg-input"
                  placeholder="tools/config/wechat_audio_cache.json"
                />
                <div class="cfg-actions">
                  <button type="button" class="btn-confirm-secondary" id="cfg-wechat-reset">
                    恢复默认
                  </button>
                  <button type="button" class="btn-confirm-secondary" id="cfg-wechat-save">
                    保存信息
                  </button>
                </div>
              </div>
            </div>
            <!-- 微信聊天模式管理 -->
            <div class="card toggle-card" style="margin-top:12px">
              <div class="toggle-row">
                <div>
                  <div class="toggle-title">微信聊天模式管理</div>
                  <div class="toggle-desc" id="wechat-mode-count">加载联系人对话模式…</div>
                </div>
              </div>
              <div id="wechat-mode-list">
                <div class="prompt-card-loading">加载中…</div>
              </div>
            </div>
          </section>
          <section class="settings-panel hidden" id="panel-wxwork" role="tabpanel" aria-labelledby="nav-wxwork">
            <h3 class="panel-title">企微设置</h3>
            <div class="card toggle-card">
              <div class="cfg-form">
                <label class="cfg-label" for="cfg-wxwork-bot-name">企微机器人名称</label>
                <input
                  type="text"
                  id="cfg-wxwork-bot-name"
                  class="cfg-input cfg-input-readonly"
                  readonly
                  tabindex="-1"
                />
                <label class="cfg-label" for="cfg-wxwork-bot-id">企微 Bot ID</label>
                <div class="cfg-input-with-toggle">
                  <input
                    type="password"
                    id="cfg-wxwork-bot-id"
                    class="cfg-input cfg-input-secret"
                    placeholder="企微 Bot ID"
                  />
                  <button type="button" class="cfg-secret-toggle" id="cfg-wxwork-bot-id-toggle" aria-label="显示/隐藏">👁</button>
                </div>
                <label class="cfg-label" for="cfg-wxwork-secret">企微 Secret</label>
                <div class="cfg-input-with-toggle">
                  <input
                    type="password"
                    id="cfg-wxwork-secret"
                    class="cfg-input cfg-input-secret"
                    placeholder="企微 Secret"
                  />
                  <button type="button" class="cfg-secret-toggle" id="cfg-wxwork-secret-toggle" aria-label="显示/隐藏">👁</button>
                </div>
                <div class="cfg-actions">
                  <button type="button" class="btn-confirm-primary" id="cfg-wxwork-connect">
                    连接
                  </button>
                  <button type="button" class="btn-confirm-danger" id="cfg-wxwork-disconnect" style="display:none;">
                    断开连接
                  </button>
                </div>
                <div class="toggle-desc" id="cfg-wxwork-connection-hint" style="margin-top:8px;"></div>
              </div>
            </div>
          </section>
          <section class="settings-panel hidden" id="panel-mcp" role="tabpanel" aria-labelledby="nav-mcp">
            <h3 class="panel-title">MCP设置</h3>
            <div class="mcp-health-card" id="mcp-health-card">
                <div class="mcp-health-head">
                  <div>
                    <div class="toggle-title">MCP 启动自检</div>
                    <div class="toggle-desc">检测当前启用的 stdio MCP 是否缺少运行命令</div>
                  </div>
                  <button type="button" class="btn-confirm-secondary" id="mcp-health-refresh">
                    刷新
                  </button>
                </div>
                <div
                  class="mcp-health-summary"
                  id="mcp-health-summary"
                  role="status"
                  aria-live="polite"
                  aria-relevant="additions text"
                  aria-atomic="true"
                >
                  正在读取自检结果…
                </div>
                <div class="mcp-health-list" id="mcp-health-missing"></div>
                <div class="mcp-health-list mcp-health-list-muted" id="mcp-health-servers"></div>
              </div>
              <div class="mcp-health-card" id="mcp-services-card">
                <div class="mcp-health-head">
                  <div>
                    <div class="toggle-title">MCP 服务及工具说明</div>
                    <div class="toggle-desc">config/mcp_servers.json — 当前所有已配置的 MCP 服务与其工具</div>
                  </div>
                  <button type="button" class="btn-confirm-secondary" id="mcp-services-refresh">
                    刷新
                  </button>
                </div>
                <div class="mcp-services-body" id="mcp-services-body">
                  <div class="prompt-card-loading">加载中…</div>
                </div>
              </div>
          </section>
          <section class="settings-panel hidden" id="panel-skills" role="tabpanel" aria-labelledby="nav-skills">
            <h3 class="panel-title">技能设置</h3>
            <div class="card" id="skills-settings-card">
              <div class="toggle-desc" id="skills-settings-hint">仅展示管理端已启用的技能（含无权限项）</div>
              <div id="skills-settings-list" class="skills-settings-list">
                <div class="pref-empty">加载中…</div>
              </div>
            </div>
          </section>
          <section class="settings-panel hidden" id="panel-templates" role="tabpanel" aria-labelledby="nav-templates">
            <h3 class="panel-title">模板管理</h3>
            <div class="card" id="templates-settings-card">
              <div class="toggle-desc" id="templates-settings-hint">查看所有可用的报告、图片、视频模板</div>
              <div id="templates-filter-tabs" class="templates-filter-tabs"></div>
              <div id="templates-settings-list" class="templates-settings-list">
                <div class="pref-empty">加载中…</div>
              </div>
            </div>
          </section>
          <section class="settings-panel hidden" id="panel-pref" role="tabpanel" aria-labelledby="nav-pref">
            <h3 class="pref-section-title" id="user-pref-section-title">
              <span>员工偏好（长期记忆）</span>
              <span class="pref-batch-slot" id="pref-batch-slot"></span>
              <button type="button" class="batch-icon-btn" id="user-pref-batch-btn" title="批量管理偏好">✓</button>
            </h3>
            <div class="card">
              <div id="user-pref-list" class="pref-list">
                <div class="pref-empty">加载中…</div>
              </div>
              <div class="pref-add-bar">
                <input type="text" id="user-pref-key-input" class="pref-input" placeholder="偏好名称（如：语言偏好）" maxlength="100" />
                <input type="text" id="user-pref-value-input" class="pref-input" placeholder="偏好内容（如：中文）" maxlength="500" />
                <button type="button" id="user-pref-add-btn">添加</button>
              </div>
              <div id="user-pref-error" class="pref-error hidden"></div>
            </div>
          </section>
        </div>
      </div>
    </div>
  </div>
  `;
}

function renderConfirmDialog() {
  return `
  <div id="confirm-overlay" class="confirm-overlay hidden" aria-hidden="true">
    <div
      class="confirm-card"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      aria-describedby="confirm-dialog-desc"
    >
      <h3 id="confirm-dialog-title" class="confirm-dialog-title">删除对话</h3>
      <p id="confirm-dialog-desc" class="confirm-dialog-desc"></p>
      <div class="confirm-dialog-actions">
        <button type="button" class="btn-confirm-secondary" id="confirm-dialog-cancel">取消</button>
        <button type="button" class="btn-confirm-danger" id="confirm-dialog-ok">删除</button>
      </div>
    </div>
  </div>
  `;
}

function renderToastHost() {
  return `
  <div id="desktop-toast-host" class="desktop-toast-host" aria-live="polite"></div>
  `;
}

export function renderAppLayout(rootEl) {
  if (!rootEl) return;
  rootEl.innerHTML =
    renderBoot() +
    renderLogin() +
    renderShell() +
    renderSkillsPanel() +
    renderSkillsManagePanel() +
    renderMcpPanel() +
    renderToastHost() +
    renderSettings() +
    renderConfirmDialog();
}
