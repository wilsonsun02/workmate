<template>
  <article class="glass-panel panel-block wide-panel">
    <div class="section-heading">
      <div>
        <h3>{{ headerTitle }}</h3>
        <p class="heading-description">集中维护该员工的账号、偏好、企微机器人、定时任务与员工设定。</p>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="detail-tabs">
      <el-tab-pane label="基本信息" name="basic">
        <UserBasicInfoTab :user="user" :departments="departments" @saved="emitSaved" />
      </el-tab-pane>
      <el-tab-pane label="账号与密码" name="account" lazy>
        <UserAccountTab :user="user" @saved="emitSaved" @deleted="emitDeleted" />
      </el-tab-pane>
      <el-tab-pane label="员工偏好" name="prefs" lazy>
        <UserPreferencesTab :user="user" :active="activeTab === 'prefs'" />
      </el-tab-pane>
      <el-tab-pane label="企微机器人" name="wxwork" lazy>
        <UserWxWorkBotTab :user="user" @saved="emitSaved" />
      </el-tab-pane>
      <el-tab-pane label="中期记忆" name="midmemory" lazy>
        <UserMidMemoryTab :user="user" @saved="emitSaved"/>
      </el-tab-pane>
      <!-- <el-tab-pane label="定时任务" name="scheduler" lazy>
        <UserSchedulerTab :user="user" />
      </el-tab-pane> -->
      <el-tab-pane label="特殊员工" name="special" lazy>
        <UserSpecialTab :user="user" @saved="emitSaved" />
      </el-tab-pane>
      <el-tab-pane label="员工设定" name="prompts" lazy>
        <CompanyDeptIdentityTab
          title="员工设定"
          :allowed-files="['identity.md']"
          default-file-name="identity.md"
          owner-type="user"
          :owner-id="user.id"
        />
      </el-tab-pane>
    </el-tabs>
  </article>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { UserItem } from '@/services/admin'
import UserAccountTab from './UserAccountTab.vue'
import UserBasicInfoTab from './UserBasicInfoTab.vue'
import UserMidMemoryTab from './UserMidMemoryTab.vue'
import UserPreferencesTab from './UserPreferencesTab.vue'
import UserSchedulerTab from './UserSchedulerTab.vue'
import UserSpecialTab from './UserSpecialTab.vue'
import UserWxWorkBotTab from './UserWxWorkBotTab.vue'
import CompanyDeptIdentityTab from './CompanyDeptIdentityTab.vue'

const props = defineProps<{
  user: UserItem
  departments: any[]
}>()

const emit = defineEmits<{
  (e: 'saved', patch?: Partial<UserItem>): void
  (e: 'deleted', userId: string): void
}>()

const activeTab = ref('basic')

const headerTitle = computed(() => {
  const displayName = props.user.name || props.user.username
  const title = String(props.user.title || '').trim()
  return title ? `${displayName} · ${title}` : displayName
})

const emitSaved = (patch?: Partial<UserItem>) => {
  emit('saved', patch)
}

const emitDeleted = (userId: string) => {
  emit('deleted', userId)
}
</script>

<style scoped>
.detail-tabs :deep(.el-tabs__content) {
  padding-top: 8px;
}
</style>
