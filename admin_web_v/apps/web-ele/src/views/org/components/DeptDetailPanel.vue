<template>
  <article class="glass-panel panel-block wide-panel">
    <div class="section-heading">
      <div>
        <h3>{{ headerTitle }}</h3>
        <p class="heading-description">查看部门基本信息，并维护部门设定（department.md）。</p>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="detail-tabs">
      <el-tab-pane label="基本信息" name="basic">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="部门名称">{{ dept.name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="部门编码">{{ dept.dept_code || '-' }}</el-descriptions-item>
          <el-descriptions-item label="上级部门">{{ parentDeptName }}</el-descriptions-item>
          <el-descriptions-item label="负责人">{{ managerName }}</el-descriptions-item>
          <el-descriptions-item label="第三方ID">{{ dept.third_party_id || '-' }}</el-descriptions-item>
        </el-descriptions>
      </el-tab-pane>
      <el-tab-pane label="部门设定（MD）" name="prompt" lazy>
        <CompanyDeptIdentityTab
          title="部门设定"
          :allowed-files="['department.md']"
          default-file-name="department.md"
          owner-type="dept"
          :owner-id="dept.id"
        />
      </el-tab-pane>
    </el-tabs>
  </article>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { DepartmentItem, UserItem } from '@/services/admin'
import CompanyDeptIdentityTab from './CompanyDeptIdentityTab.vue'

const props = defineProps<{
  dept: DepartmentItem
  departments: DepartmentItem[]
  members: UserItem[]
}>()

const activeTab = ref<'basic' | 'prompt'>('basic')

const parentDeptName = computed(() => {
  const parentId = String(props.dept.parent_id || '').trim()
  if (!parentId) return '-'
  const parent = props.departments.find((item) => String(item.id || '').trim() === parentId)
  return parent?.name || '-'
})

const managerName = computed(() => {
  const managerId = String(props.dept.manager_user_id || '').trim()
  if (!managerId) return '-'
  const user = props.members.find((item) => String(item.id || '').trim() === managerId)
  return user ? (user.name || user.username || user.id) : managerId
})

const headerTitle = computed(() => {
  const deptName = props.dept.name || '部门'
  const code = String(props.dept.dept_code || '').trim()
  return code ? `${deptName} · ${code}` : deptName
})
</script>

<style scoped>
.detail-tabs :deep(.el-tabs__content) {
  padding-top: 8px;
}
</style>
