<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { reactive, ref, watch } from 'vue'

import { useUserStore } from '@/stores/user'
import type { User } from '@/types/user'
import { getErrorMessage } from '@/utils/error'
import defaultAvatar from '@/assets/default-avatar.png'

const props = defineProps<{ modelValue: boolean; user: User | null }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()
const userStore = useUserStore()
const profile = reactive({ username: '', email: '', currentPassword: '' })
const password = reactive({ currentPassword: '', newPassword: '', confirmPassword: '' })
const avatarLoading = ref(false)
const fileInput = ref<HTMLInputElement>()

watch(
  () => [props.modelValue, props.user] as const,
  () => {
    if (!props.modelValue || !props.user) return
    profile.username = props.user.username
    profile.email = props.user.email || ''
    profile.currentPassword = ''
    password.currentPassword = ''
    password.newPassword = ''
    password.confirmPassword = ''
  },
  { immediate: true },
)

async function saveProfile(): Promise<void> {
  if (!profile.username.trim() || !profile.email.trim() || !profile.currentPassword) {
    ElMessage.warning('请完整填写资料和当前密码')
    return
  }
  try {
    await userStore.updateProfile(profile)
    profile.currentPassword = ''
    ElMessage.success('个人资料已更新')
  } catch (reason) {
    ElMessage.error(getErrorMessage(reason, '个人资料更新失败'))
  }
}

async function savePassword(): Promise<void> {
  if (password.newPassword.length < 8) {
    ElMessage.warning('新密码长度不能少于 8 位')
    return
  }
  if (password.newPassword !== password.confirmPassword) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  try {
    await userStore.updatePassword(password)
    password.currentPassword = ''
    password.newPassword = ''
    password.confirmPassword = ''
    ElMessage.success('密码已修改')
  } catch (reason) {
    ElMessage.error(getErrorMessage(reason, '密码修改失败'))
  }
}

function openAvatarPicker(): void {
  fileInput.value?.click()
}

async function selectAvatar(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
    ElMessage.warning('请选择 PNG、JPEG 或 WebP 图片')
    return
  }
  if (file.size > 2 * 1024 * 1024) {
    ElMessage.warning('头像大小不能超过 2 MB')
    return
  }
  avatarLoading.value = true
  try {
    const dataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result))
      reader.onerror = () => reject(reader.error)
      reader.readAsDataURL(file)
    })
    await userStore.updateAvatar(dataUrl)
    ElMessage.success('头像已更新')
  } catch (reason) {
    ElMessage.error(getErrorMessage(reason, '头像更新失败'))
  } finally {
    avatarLoading.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="个人资料"
    width="520px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-tabs>
      <el-tab-pane label="头像">
        <div class="avatar-editor">
          <div class="avatar-editor__preview">
            <img :src="user?.avatarUrl || defaultAvatar" alt="当前头像" />
          </div>
          <p>支持 PNG、JPEG、WebP，文件大小不超过 2 MB。</p>
          <input
            ref="fileInput"
            accept="image/png,image/jpeg,image/webp"
            class="avatar-editor__input"
            type="file"
            @change="selectAvatar"
          />
          <el-button :loading="avatarLoading" type="primary" @click="openAvatarPicker">
            选择新头像
          </el-button>
        </div>
      </el-tab-pane>
      <el-tab-pane label="基本资料">
        <el-form label-position="top">
          <el-form-item label="用户名"><el-input v-model="profile.username" /></el-form-item>
          <el-form-item label="邮箱"
            ><el-input v-model="profile.email" type="email"
          /></el-form-item>
          <el-form-item label="当前密码">
            <el-input v-model="profile.currentPassword" show-password type="password" />
          </el-form-item>
          <el-button type="primary" @click="saveProfile">保存资料</el-button>
        </el-form>
      </el-tab-pane>
      <el-tab-pane label="修改密码">
        <el-form label-position="top">
          <el-form-item label="当前密码">
            <el-input v-model="password.currentPassword" show-password type="password" />
          </el-form-item>
          <el-form-item label="新密码">
            <el-input v-model="password.newPassword" show-password type="password" />
          </el-form-item>
          <el-form-item label="确认新密码">
            <el-input v-model="password.confirmPassword" show-password type="password" />
          </el-form-item>
          <el-button type="primary" @click="savePassword">修改密码</el-button>
        </el-form>
      </el-tab-pane>
    </el-tabs>
  </el-dialog>
</template>

<style scoped>
.avatar-editor {
  display: flex;
  align-items: center;
  flex-direction: column;
  padding: 20px 0 28px;
}

.avatar-editor__preview {
  display: grid;
  width: 112px;
  height: 112px;
  place-items: center;
  overflow: hidden;
  border-radius: 50%;
  color: #fff;
  background: #334155;
  font-size: 36px;
  font-weight: 800;
}

.avatar-editor__preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.avatar-editor p {
  margin: 16px 0;
  color: var(--color-text-secondary);
  font-size: 13px;
}

.avatar-editor__input {
  display: none;
}
</style>
