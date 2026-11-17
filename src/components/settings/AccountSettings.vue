<script setup lang="ts">
import { Camera, KeyRound, UserRound } from 'lucide-vue-next'
import ActionButton from '../ui/ActionButton.vue'
import SettingsSection from './SettingsSection.vue'
import { languageOptions } from '../../mock/settings'
import type { UserProfile } from '../../types/settings'

const props = defineProps<{ profile: UserProfile; avatarUrl?: string; workstation?: boolean }>()
const emit = defineEmits<{
  'update:profile': [profile: UserProfile]
  avatar: [url: string]
  password: []
}>()

function update(field: keyof UserProfile, value: string) {
  emit('update:profile', { ...props.profile, [field]: value })
}
function onAvatar(event: Event) { emit('avatar', (event.target as HTMLInputElement).value) }
</script>

<template>
  <SettingsSection title="账户" description="管理你的个人资料与账户访问。">
    <div class="settings-card profile-card">
      <div class="profile-card__top">
        <div class="profile-avatar" aria-label="当前头像">
          <img v-if="avatarUrl" :src="avatarUrl" alt="账户头像" />
          <UserRound v-else :size="26" :stroke-width="1.6" />
        </div>
        <div class="profile-card__identity"><strong>{{ workstation && profile.username === 'local' ? '本机工作区' : profile.username }}</strong><span class="faint">{{ workstation ? '本机工作区' : '个人账户' }}</span></div>
        <label class="profile-avatar-picker btn btn-ghost btn-sm">
          <Camera :size="14" />更换头像
          <input type="url" :value="avatarUrl" aria-label="头像 URL" placeholder="https://..." @change="onAvatar" />
        </label>
      </div>
      <div class="settings-field-grid profile-fields">
        <label class="settings-field"><span>用户名</span><input :value="profile.username" maxlength="80" aria-label="用户名" @change="update('username', ($event.target as HTMLInputElement).value)" /></label>
        <label class="settings-field"><span>部署时区</span><input :value="profile.timezone" readonly aria-label="部署时区" aria-describedby="deployment-timezone-description" /><small id="deployment-timezone-description">部署时区由服务端 APP_TIMEZONE 决定，此处不可修改</small></label>
        <label class="settings-field"><span>语言</span><select :value="profile.language" @change="update('language', ($event.target as HTMLSelectElement).value)"><option v-for="language in languageOptions" :key="language" :value="language">{{ language }}</option></select></label>
      </div>
    </div>
    <div v-if="!workstation" class="settings-button-row" style="margin-top:0">
      <ActionButton variant="secondary" @click="emit('password')"><KeyRound :size="15" />修改密码</ActionButton>
    </div>
  </SettingsSection>
</template>

<style scoped>
.profile-card__top { display: flex; align-items: center; gap: 14px; min-width: 0; flex-wrap: wrap; }
.profile-avatar { display: grid; width: 52px; height: 52px; flex: none; overflow: hidden; place-items: center; border-radius: 50%; color: var(--accent); background: var(--accent-soft); }
.profile-avatar img { width: 100%; height: 100%; object-fit: cover; }
.profile-card__identity { display: flex; flex-direction: column; min-width: 0; gap: 2px; }
.profile-card__identity strong { color: var(--text); font-size: 16px; font-weight: 650; }
.profile-card__identity span { font-size: 12px; }
.profile-avatar-picker { margin-left: auto; position: relative; cursor: pointer; }
.profile-avatar-picker input { width: 110px; min-width: 0; border: 0; background: transparent; font-size: 11px; outline: none; }
.profile-fields { margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--line); }
</style>
