<script lang="ts" setup>
import type { VbenFormSchema } from '@vben/common-ui';

import { computed, ref } from 'vue';

import { AuthenticationLogin, z } from '@vben/common-ui';

import { useAuthStore } from '#/store';

defineOptions({ name: 'Login' });

const authStore = useAuthStore();
const loginErrorMsg = ref('');

async function handleLogin(params: Record<string, any>) {
  loginErrorMsg.value = '';
  try {
    await authStore.authLogin(params);
  } catch {
    loginErrorMsg.value = authStore.loginError || '登录失败，请检查账号或密码';
  }
}

const formSchema = computed((): VbenFormSchema[] => {
  return [
    {
      component: 'VbenInput',
      componentProps: {
        placeholder: '请输入管理员账号',
      },
      fieldName: 'username',
      label: '账号',
      rules: z.string().min(1, { message: '请输入管理员账号' }),
    },
    {
      component: 'VbenInputPassword',
      componentProps: {
        placeholder: '请输入密码',
      },
      fieldName: 'password',
      label: '密码',
      rules: z.string().min(1, { message: '请输入密码' }),
    },
  ];
});
</script>

<template>
  <AuthenticationLogin
    :form-schema="formSchema"
    :loading="authStore.loginLoading"
    page-sub-title="统一管理配置、用户、客户端与技能能力"
    page-title="WorkMate"
    :show-code-login="false"
    :show-forget-password="false"
    :show-qrcode-login="false"
    :show-register="false"
    :show-third-party-login="false"
    @submit="handleLogin"
  >
    <template #subTitle>
      统一管理配置、用户、客户端与技能能力
      <div
        v-if="loginErrorMsg"
        style="
          margin-top: 10px;
          padding: 8px 12px;
          background: #fff2f0;
          border: 1px solid #ffccc7;
          border-radius: 6px;
          color: #ff4d4f;
          font-size: 13px;
          line-height: 1.5;
        "
      >
        {{ loginErrorMsg }}
      </div>
    </template>
  </AuthenticationLogin>
</template>
