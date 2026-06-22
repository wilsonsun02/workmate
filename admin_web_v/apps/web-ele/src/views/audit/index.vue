<template>
  <div class="page-grid">
    <!-- 顶部标题和统计 -->
    <section class="section-banner glass-panel compact-banner">
      <div>
        <div class="eyebrow">Security & Compliance</div>
        <h2>安全合规</h2>
      </div>
      <div class="stats-cards">
        <div class="stat-card">
          <span class="stat-value">{{ stats.total }}</span>
          <span class="stat-label">总拦截数</span>
        </div>
        <div class="stat-card">
          <span class="stat-value">{{ stats.today }}</span>
          <span class="stat-label">今日拦截</span>
        </div>
      </div>
    </section>

    <!-- 筛选条件 -->
    <section class="glass-panel panel-block">
      <div class="section-heading">
        <div>
          <div class="eyebrow">Security Events</div>
          <h3>拦截日志</h3>
        </div>
      </div>

      <div class="filter-bar">
        <el-input v-model="filters.keyword" placeholder="搜索用户或内容" clearable style="width: 200px" @keyup.enter="loadLogs" />
        <el-select v-model="filters.channel" placeholder="渠道" clearable style="width: 130px" @change="loadLogs">
          <el-option label="微信" value="wechat" />
          <el-option label="企微" value="wxwork" />
        </el-select>
        <el-select v-model="filters.intercept_type" placeholder="拦截类型" clearable style="width: 140px" @change="loadLogs">
          <el-option label="关键词扫描" value="keyword" />
          <el-option label="LLM审查" value="llm_review" />
        </el-select>
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYY-MM-DD"
          style="width: 260px"
          @change="loadLogs"
        />
        <el-button type="primary" @click="loadLogs">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
      </div>

      <el-table :data="logs" border stripe row-key="id" v-loading="loading">
        <el-table-column prop="created_at" label="拦截时间" min-width="170" />
        <el-table-column prop="username" label="操作用户" min-width="100" />
        <el-table-column label="渠道" min-width="80">
          <template #default="scope">
            <el-tag round size="small">{{ channelLabel(scope.row.channel) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="拦截类型" min-width="100">
          <template #default="scope">
            <el-tag round :type="scope.row.intercept_type === 'keyword' ? 'danger' : 'warning'" size="small">
              {{ interceptTypeLabel(scope.row.intercept_type) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="tool_name" label="触发工具" min-width="200" show-overflow-tooltip />
        <el-table-column label="违规项" min-width="220">
          <template #default="scope">
            <div class="violation-tags">
              <el-tag v-for="(v, i) in scope.row.violations" :key="i" type="danger" size="small" round style="margin: 2px">
                {{ v }}
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="内容摘要" min-width="200">
          <template #default="scope">
            <span class="content-summary">{{ contentSummary(scope.row.raw_content) }}</span>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pagination-bar">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @size-change="loadLogs"
          @current-change="loadLogs"
        />
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { adminApi } from '@/services/admin'

// 筛选条件
const filters = ref({
  keyword: '',
  channel: '',
  intercept_type: '',
})
const dateRange = ref<string[]>([])

// 数据
const logs = ref<any[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const loading = ref(false)

// 统计
const stats = ref<{ total: number; today: number; by_channel: { channel: string; count: number }[]; by_type: { intercept_type: string; count: number }[] }>({
  total: 0,
  today: 0,
  by_channel: [],
  by_type: [],
})

// 渠道标签映射
const channelLabel = (channel: string) => {
  const map: Record<string, string> = { wechat: '微信', wxwork: '企微', unknown: '未知' }
  return map[channel] || channel
}

// 拦截类型标签映射
const interceptTypeLabel = (type: string) => {
  const map: Record<string, string> = { keyword: '关键词', llm_review: 'LLM审查' }
  return map[type] || type
}

// 内容摘要：截取前80字
const contentSummary = (content: string) => {
  if (!content) return '-'
  return content.length > 80 ? content.slice(0, 80) + '...' : content
}

// 加载拦截日志
const loadLogs = async () => {
  loading.value = true
  try {
    const params: any = {
      limit: pageSize.value,
      offset: (currentPage.value - 1) * pageSize.value,
    }
    if (filters.value.keyword) params.keyword = filters.value.keyword
    if (filters.value.channel) params.channel = filters.value.channel
    if (filters.value.intercept_type) params.intercept_type = filters.value.intercept_type
    if (dateRange.value && dateRange.value.length === 2) {
      params.start_time = dateRange.value[0] + ' 00:00:00'
      params.end_time = dateRange.value[1] + ' 23:59:59'
    }

    const res = await adminApi.getInterceptLogs(params)
    if (res.success) {
      logs.value = res.logs || []
      total.value = res.total || 0
    }
  } catch (e) {
    console.error('加载拦截日志失败', e)
  } finally {
    loading.value = false
  }
}

// 加载统计数据
const loadStats = async () => {
  try {
    const res = await adminApi.getInterceptStats()
    if (res.success) {
      stats.value = res.stats
    }
  } catch (e) {
    console.error('加载统计失败', e)
  }
}

// 重置筛选
const resetFilters = () => {
  filters.value = { keyword: '', channel: '', intercept_type: '' }
  dateRange.value = []
  currentPage.value = 1
  loadLogs()
}

onMounted(() => {
  loadLogs()
  loadStats()
})
</script>

<style scoped>
.stats-cards {
  display: flex;
  gap: 24px;
  align-items: center;
}
.stat-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 20px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 8px;
}
.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--el-color-primary);
}
.stat-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}
.filter-bar {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.violation-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
}
.content-summary {
  color: var(--el-text-color-regular);
  font-size: 13px;
}
.pagination-bar {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
