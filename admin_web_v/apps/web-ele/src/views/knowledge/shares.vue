<template>
  <div class="page-grid kb-page">
    <section class="glass-panel panel-block">
      <div class="section-heading section-heading--table">
        <div>
          <div class="eyebrow">Knowledge Sharing</div>
          <h2>知识库分享记录</h2>
          <p class="heading-description">
            查看和管理全公司知识库文件分享记录，支持按分享人、被分享人筛选。
          </p>
        </div>
        <div class="heading-tags">
          <el-tag type="info">{{ total }} 条记录</el-tag>
        </div>
      </div>

      <div class="toolbar-row">
        <el-input
          v-model="filters.keyword"
          clearable
          placeholder="搜索文件名"
          class="search-input"
          style="width: 200px"
          @keyup.enter="fetchShares"
          @clear="fetchShares"
        />
        <el-input
          v-model="filters.owner"
          clearable
          placeholder="分享人"
          style="width: 140px"
          @keyup.enter="fetchShares"
          @clear="fetchShares"
        />
        <el-input
          v-model="filters.target"
          clearable
          placeholder="被分享人"
          style="width: 140px"
          @keyup.enter="fetchShares"
          @clear="fetchShares"
        />
        <el-button type="primary" plain :loading="fetching" @click="fetchShares">查询</el-button>
      </div>

      <el-table
        v-loading="fetching"
        :data="shares"
        border
        stripe
        row-key="share_id"
        table-layout="fixed"
        size="small"
        :header-cell-style="{ background: '#fafafa', fontWeight: '600', padding: '8px 12px' }"
        :cell-style="{ padding: '8px 12px', verticalAlign: 'middle' }"
      >
        <el-table-column label="文件名" min-width="200">
          <template #default="{ row }">
            <span>{{ row.original_filename || row.md_filename }}</span>
          </template>
        </el-table-column>
        <el-table-column label="分类" width="140">
          <template #default="{ row }">
            <el-tag size="small">{{ row.share_category }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="分享人" width="120">
          <template #default="{ row }">
            <span>{{ row.owner_username }}</span>
          </template>
        </el-table-column>
        <el-table-column label="被分享人" width="120">
          <template #default="{ row }">
            <span>{{ row.target_username }}</span>
          </template>
        </el-table-column>
        <el-table-column label="文件类型" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" type="info">{{ row.file_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="摘要" min-width="180">
          <template #default="{ row }">
            <el-tooltip :content="row.summary" placement="top" :show-after="300" :disabled="!row.summary">
              <span class="cell-text-ellipsis">{{ row.summary || '暂无摘要' }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="分享时间" width="170">
          <template #default="{ row }">
            <span>{{ row.shared_at }}</span>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="total > pageSize" class="pagination-row">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="total"
          layout="prev, pager, next"
          @current-change="fetchShares"
        />
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
// @ts-nocheck
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi, type KbShareItem } from '@/services/admin'

const shares = ref<KbShareItem[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = 20
const fetching = ref(false)

const filters = reactive({
  keyword: '',
  owner: '',
  target: '',
})

const fetchShares = async () => {
  fetching.value = true
  try {
    const res = await adminApi.getKbShares({
      page: currentPage.value,
      size: pageSize,
      keyword: filters.keyword,
      owner: filters.owner,
      target: filters.target,
    })
    if (res.success) {
      shares.value = res.items || []
      total.value = res.total || 0
    }
  } catch (e: any) {
    ElMessage.error('获取分享记录失败')
  } finally {
    fetching.value = false
  }
}

onMounted(() => {
  fetchShares()
})
</script>

<style scoped>
.kb-page {
  padding: 0;
}

.toolbar-row {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.pagination-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.cell-text-ellipsis {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:deep(.el-table .cell) {
  font-size: 13px;
  line-height: 1.5;
}

:deep(.el-table .el-tag--small) {
  vertical-align: middle;
}
</style>
