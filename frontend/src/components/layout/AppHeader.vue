<script setup lang="ts">
import BrandLogo from '@/components/common/BrandLogo.vue'
import defaultAvatar from '@/assets/default-avatar.png'

withDefaults(
  defineProps<{
    username?: string
    avatarUrl?: string
  }>(),
  {
    username: '当前用户',
    avatarUrl: undefined,
  },
)

defineEmits<{
  profile: []
  logout: []
}>()
</script>

<template>
  <header class="app-header">
    <BrandLogo compact />

    <div class="app-header__actions">
      <span class="app-header__environment">知识库问答</span>
      <span class="app-header__divider" aria-hidden="true" />
      <el-dropdown trigger="click">
        <button class="app-header__user" type="button">
          <span class="app-header__avatar">
            <img :alt="`${username}的头像`" :src="avatarUrl || defaultAvatar" />
          </span>
          <span>{{ username }}</span>
          <span class="app-header__chevron" aria-hidden="true">⌄</span>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item @click="$emit('profile')">个人资料</el-dropdown-item>
            <el-dropdown-item divided @click="$emit('logout')">退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  position: relative;
  z-index: 10;
  display: flex;
  height: var(--header-height);
  align-items: center;
  justify-content: space-between;
  padding: 0 28px;
  border-bottom: 1px solid var(--color-border);
  background: rgb(255 255 255 / 94%);
  box-shadow: 0 1px 2px rgb(15 23 42 / 3%);
}

.app-header__actions,
.app-header__user {
  display: flex;
  align-items: center;
}

.app-header__actions {
  gap: 18px;
}

.app-header__environment {
  padding: 7px 11px;
  border: 1px solid #dbeafe;
  border-radius: 999px;
  color: var(--color-primary-dark);
  background: #eff6ff;
  font-size: 12px;
  font-weight: 700;
}

.app-header__divider {
  width: 1px;
  height: 26px;
  background: var(--color-border);
}

.app-header__user {
  gap: 10px;
  padding: 5px 8px 5px 5px;
  border: 0;
  border-radius: 10px;
  color: var(--color-text);
  background: transparent;
  cursor: pointer;
}

.app-header__user:hover {
  background: #f8fafc;
}

.app-header__avatar {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border-radius: 50%;
  color: #fff;
  background: #334155;
  font-size: 13px;
  font-weight: 800;
}

.app-header__avatar img {
  width: 100%;
  height: 100%;
  border-radius: inherit;
  object-fit: cover;
}

.app-header__chevron {
  color: #98a2b3;
  font-size: 16px;
}
</style>
