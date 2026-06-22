<script lang="ts" setup>
import { useElementPlusDesignTokens } from '@vben/hooks';

import { ElConfigProvider } from 'element-plus';

import { elementLocale } from '#/locales';
import './styles/admin-pages.css';

defineOptions({ name: 'App' });

useElementPlusDesignTokens();
</script>

<template>
  <ElConfigProvider :locale="elementLocale">
    <RouterView />
  </ElConfigProvider>
</template>

<style>
.el-popper:not(.is-dark) {
  background-color: var(--el-bg-color-overlay, var(--el-bg-color)) !important;
}
</style>
