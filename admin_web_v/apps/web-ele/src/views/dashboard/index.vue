<template>
  <div class="page-grid">
    <section class="hero-panel glass-panel">
      <div>
        <div class="eyebrow">Operations Overview</div>
        <h2>统一掌控模型、调度、审计与企业协同。</h2>
        <p>
          admin-web2 延续原有管理能力，但把关键状态、告警优先级与配置入口集中到更清晰的视觉层级里。
        </p>
      </div>
      <div class="hero-metrics">
        <div class="hero-chip">
          <span>今日任务成功率</span>
          <strong>98.6%</strong>
        </div>
        <div class="hero-chip">
          <span>活跃线程</span>
          <strong>24</strong>
        </div>
      </div>
    </section>

    <section class="stats-grid">
      <article v-for="item in dashboardStats" :key="item.label" class="metric-card glass-panel">
        <span class="metric-label">{{ item.label }}</span>
        <strong class="metric-value">{{ item.value }}</strong>
        <span class="metric-trend" :class="`tone-${item.tone}`">{{ item.trend }}</span>
      </article>
    </section>

    <section class="content-grid two-column">
      <article class="glass-panel panel-block">
        <div class="section-heading">
          <div>
            <div class="eyebrow">Highlights</div>
            <h3>关键关注项</h3>
          </div>
          <el-tag round type="success">系统稳定</el-tag>
        </div>
        <div class="focus-list">
          <div v-for="item in dashboardFocus" :key="item.title" class="focus-item">
            <div>
              <strong>{{ item.title }}</strong>
              <p>{{ item.detail }}</p>
            </div>
            <span>{{ item.value }}</span>
          </div>
        </div>
      </article>

      <article class="glass-panel panel-block">
        <div class="section-heading">
          <div>
            <div class="eyebrow">Timeline</div>
            <h3>今日运行动态</h3>
          </div>
        </div>
        <div class="timeline-list">
          <div v-for="item in dashboardTimeline" :key="item.time" class="timeline-item">
            <div class="timeline-time">{{ item.time }}</div>
            <div>
              <strong>{{ item.title }}</strong>
              <p>{{ item.detail }}</p>
            </div>
          </div>
        </div>
      </article>
    </section>
  </div>
</template>

<script setup lang="ts">
import { dashboardFocus, dashboardStats, dashboardTimeline } from '@/data/mock'
</script>
