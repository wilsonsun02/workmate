<template>
  <div class="page-grid">
    <section class="section-banner glass-panel compact-banner">
      <div>
        <div class="eyebrow">Security Rules</div>
        <h2>规则配置</h2>
      </div>
      <div class="banner-actions">
        <el-button type="primary" :loading="saving" @click="handleSave">保存配置</el-button>
      </div>
    </section>

    <div v-loading="loading" class="rules-layout">
      <!-- 左侧：基础设置 -->
      <section class="glass-panel panel-block">
        <div class="section-heading">
          <div>
            <div class="eyebrow">General</div>
            <h3>基础设置</h3>
          </div>
        </div>

        <el-form label-width="120px" label-position="top">
          <el-form-item label="启用安全检查">
            <el-switch v-model="form.enabled" />
          </el-form-item>

          <el-form-item label="拦截渠道">
            <el-checkbox-group v-model="form.channels">
              <el-checkbox label="wechat">微信</el-checkbox>
              <el-checkbox label="wechat_work">企微</el-checkbox>
            </el-checkbox-group>
          </el-form-item>

          <el-form-item label="违规动作">
            <el-select v-model="form.violation_action" style="width: 200px">
              <el-option label="拦截 (block)" value="block" />
              <el-option label="警告 (warn)" value="warn" />
            </el-select>
          </el-form-item>
        </el-form>
      </section>

      <!-- 关键词黑名单 -->
      <section class="glass-panel panel-block">
        <div class="section-heading">
          <div>
            <div class="eyebrow">Keywords</div>
            <h3>关键词黑名单</h3>
          </div>
        </div>

        <div class="tag-editor">
          <el-tag
            v-for="(kw, idx) in form.keywords_blacklist"
            :key="idx"
            closable
            type="danger"
            size="large"
            style="margin: 4px"
            @close="removeKeyword(idx)"
          >
            {{ kw }}
          </el-tag>
          <el-input
            v-if="keywordInputVisible"
            ref="keywordInputRef"
            v-model="keywordInputValue"
            size="small"
            style="width: 160px"
            placeholder="输入关键词"
            @keyup.enter="addKeyword"
            @blur="addKeyword"
          />
          <el-button v-else size="small" @click="showKeywordInput">+ 添加关键词</el-button>
        </div>
      </section>

      <!-- 自定义规则 -->
      <section class="glass-panel panel-block">
        <div class="section-heading">
          <div>
            <div class="eyebrow">Custom Rules</div>
            <h3>自定义规则</h3>
          </div>
        </div>

        <div class="rule-list">
          <div v-for="(rule, idx) in form.custom_rules" :key="idx" class="rule-item">
            <el-input v-model="form.custom_rules[idx]" placeholder="输入规则描述" />
            <el-button type="danger" text @click="form.custom_rules.splice(idx, 1)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
          <el-button size="small" @click="form.custom_rules.push('')">+ 添加规则</el-button>
        </div>
      </section>

      <!-- 通知设置 -->
      <section class="glass-panel panel-block">
        <div class="section-heading">
          <div>
            <div class="eyebrow">Notification</div>
            <h3>通知设置</h3>
          </div>
        </div>

        <el-form label-position="top">
          <el-form-item label="通知工作伙伴">
            <el-switch v-model="form.notify_owner" />
          </el-form-item>

          <el-form-item label="通知消息模板">
            <el-input
              v-model="form.owner_notify_message"
              type="textarea"
              :rows="2"
              placeholder="支持 {violations} 占位符"
            />
          </el-form-item>

          <el-form-item label="客户端安全提示语">
            <el-input
              v-model="form.client_safe_message"
              type="textarea"
              :rows="2"
            />
          </el-form-item>
        </el-form>
      </section>

      <!-- LLM 审查设置 -->
      <section class="glass-panel panel-block">
        <div class="section-heading">
          <div>
            <div class="eyebrow">LLM Review</div>
            <h3>LLM 审查设置</h3>
          </div>
        </div>

        <el-form label-position="top">
          <el-form-item label="启用 LLM 审查">
            <el-switch v-model="form.llm_review_enabled" />
          </el-form-item>

          <el-form-item label="审查 Prompt 模板">
            <el-input
              v-model="form.llm_review_prompt_template"
              type="textarea"
              :rows="8"
              placeholder="支持 {rules} 和 {content} 占位符"
            />
          </el-form-item>
        </el-form>
      </section>

      <!-- 工具-渠道映射 -->
      <section class="glass-panel panel-block">
        <div class="section-heading">
          <div>
            <div class="eyebrow">Tool Mapping</div>
            <h3>工具-渠道映射</h3>
          </div>
        </div>

        <div class="mapping-list">
          <div v-for="(channel, tool) in form.tool_channel_mapping" :key="tool" class="mapping-item">
            <el-input :model-value="tool" disabled style="width: 320px" />
            <el-select :model-value="channel" style="width: 140px" @change="(v: string) => form.tool_channel_mapping[tool] = v">
              <el-option label="微信" value="wechat" />
              <el-option label="企微" value="wxwork" />
            </el-select>
            <el-button type="danger" text @click="delete form.tool_channel_mapping[tool]">
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
          <div class="mapping-add">
            <el-input v-model="newMappingTool" placeholder="工具名" style="width: 320px" />
            <el-select v-model="newMappingChannel" style="width: 140px">
              <el-option label="微信" value="wechat" />
              <el-option label="企微" value="wxwork" />
            </el-select>
            <el-button size="small" type="primary" @click="addMapping">添加</el-button>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, nextTick, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'
import { adminApi } from '#/services/admin'

// 表单数据
const form = reactive({
  enabled: true,
  channels: ['wechat', 'wechat_work'] as string[],
  tool_channel_mapping: {} as Record<string, string>,
  keywords_blacklist: [] as string[],
  custom_rules: [] as string[],
  violation_action: 'block',
  notify_owner: true,
  owner_notify_message: '',
  client_safe_message: '',
  llm_review_enabled: true,
  llm_review_prompt_template: '',
})

const loading = ref(false)
const saving = ref(false)

// 关键词输入
const keywordInputVisible = ref(false)
const keywordInputValue = ref('')
const keywordInputRef = ref<any>(null)

// 工具映射新增
const newMappingTool = ref('')
const newMappingChannel = ref('wechat')

// 加载规则配置
async function loadRules() {
  loading.value = true
  try {
    const res = await adminApi.getSecurityRules()
    if (res.success && res.rules) {
      const r = res.rules
      form.enabled = r.enabled ?? true
      form.channels = r.channels ?? ['wechat', 'wechat_work']
      form.tool_channel_mapping = r.tool_channel_mapping ?? {}
      form.keywords_blacklist = r.keywords_blacklist ?? []
      form.custom_rules = r.custom_rules ?? []
      form.violation_action = r.violation_action ?? 'block'
      form.notify_owner = r.notify_owner ?? true
      form.owner_notify_message = r.owner_notify_message ?? ''
      form.client_safe_message = r.client_safe_message ?? ''
      form.llm_review_enabled = r.llm_review_enabled ?? true
      form.llm_review_prompt_template = r.llm_review_prompt_template ?? ''
    }
  } catch (e: any) {
    ElMessage.error('加载规则失败: ' + (e.message || e))
  } finally {
    loading.value = false
  }
}

// 保存规则配置
async function handleSave() {
  saving.value = true
  try {
    const res = await adminApi.saveSecurityRules({ ...form })
    if (res.success) {
      ElMessage.success('规则已保存')
    } else {
      ElMessage.error('保存失败')
    }
  } catch (e: any) {
    ElMessage.error('保存失败: ' + (e.message || e))
  } finally {
    saving.value = false
  }
}

// 关键词操作
function showKeywordInput() {
  keywordInputVisible.value = true
  nextTick(() => keywordInputRef.value?.focus())
}

function addKeyword() {
  const val = keywordInputValue.value.trim()
  if (val && !form.keywords_blacklist.includes(val)) {
    form.keywords_blacklist.push(val)
  }
  keywordInputVisible.value = false
  keywordInputValue.value = ''
}

function removeKeyword(idx: number) {
  form.keywords_blacklist.splice(idx, 1)
}

// 工具映射操作
function addMapping() {
  const tool = newMappingTool.value.trim()
  if (tool && !form.tool_channel_mapping[tool]) {
    form.tool_channel_mapping[tool] = newMappingChannel.value
    newMappingTool.value = ''
  }
}

onMounted(loadRules)
</script>

<style scoped>
.page-grid {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
}

.section-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.banner-actions {
  display: flex;
  gap: 8px;
}

.rules-layout {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.rules-layout .panel-block:first-child {
  grid-column: 1 / -1;
}

.tag-editor {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}

.rule-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.rule-item {
  display: flex;
  gap: 8px;
  align-items: center;
}

.mapping-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.mapping-item {
  display: flex;
  gap: 8px;
  align-items: center;
}

.mapping-add {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 8px;
}

.eyebrow {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: var(--el-text-color-secondary);
  margin-bottom: 2px;
}

.section-heading h3 {
  margin: 0;
  font-size: 16px;
}

.glass-panel {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 20px;
}

.compact-banner {
  padding: 16px 20px;
}
</style>
