<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <main class="placeholder-page">
    <section class="placeholder-card">
      <p class="placeholder-card__eyebrow">404</p>
      <h1>页面不存在</h1>
      <p>当前地址无法访问，请返回聊天首页。</p>
      <el-button type="primary" @click="router.push('/chat')"> 返回首页 </el-button>
    </section>
  </main>
</template>
