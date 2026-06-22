<template>
  <div class="page-grid">
    <section class="section-banner glass-panel compact-banner">
      <div>
        <div class="eyebrow">Cost Center</div>
        <h2>查看消耗结构与额度使用率</h2>
      </div>
      <div class="banner-stats triple">
        <div v-for="item in costStats" :key="item.label">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
          <em>{{ item.unit }}</em>
        </div>
      </div>
    </section>

    <section class="content-grid two-column">
      <article class="glass-panel panel-block">
        <div class="section-heading">
          <div>
            <div class="eyebrow">Quota Usage</div>
            <h3>用户额度使用情况</h3>
          </div>
        </div>
        <el-table :data="costBreakdown">
          <el-table-column prop="user" label="用户" min-width="120" />
          <el-table-column prop="department" label="所属部门" min-width="120" />
          <el-table-column prop="used" label="已用 Token" min-width="140" />
          <el-table-column prop="quota" label="总额度" min-width="140" />
          <el-table-column label="使用率" min-width="180">
            <template #default="scope">
              <el-progress
                :percentage="Math.round((scope.row.used / scope.row.quota) * 100)"
                :status="scope.row.used / scope.row.quota > 0.9 ? 'exception' : ''"
              />
            </template>
          </el-table-column>
          <el-table-column prop="cost" label="预估费用(¥)" min-width="130" />
        </el-table>
      </article>

      <article class="glass-panel panel-block info-rail">
        <div class="section-heading">
          <div>
            <div class="eyebrow">Insights</div>
            <h3>成本观察</h3>
          </div>
        </div>
        <div class="check-list">
          <div class="check-item">
            <strong>研发中台消耗最高</strong>
            <p>主要来自长上下文问答与批量文档处理任务。</p>
          </div>
          <div class="check-item">
            <strong>限流事件 12 次</strong>
            <p>建议对高峰时段任务队列做优先级分流。</p>
          </div>
          <div class="check-item">
            <strong>预算仍可控</strong>
            <p>按当前趋势，本月费用预计维持在 50 元内。</p>
          </div>
        </div>
      </article>
    </section>
  </div>
</template>

<script setup lang="ts">
import { costBreakdown, costStats } from '@/data/mock'
</script>
