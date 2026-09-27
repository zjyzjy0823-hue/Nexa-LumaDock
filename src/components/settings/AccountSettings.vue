<script setup lang="ts">
import { Camera, KeyRound, LogOut, UserRound } from 'lucide-vue-next'
import ActionButton from '../ui/ActionButton.vue'
import Input from '../ui/Input.vue'
import SettingsSection from './SettingsSection.vue'
import { languageOptions, timezoneOptions } from '../../mock/settings'
import type { UserProfile } from '../../types/settings'

const props = defineProps<{ profile: UserProfile; avatarUrl?: string }>()
const emit = defineEmits<{
  'update:profile': [profile: UserProfile]
  avatar: [file: File]
  password: []
  logout: []
}>()

function update(field: keyof UserProfile, value: string) {
  emit('update:profile', { ...props.profile, [field]: value })
}
function onAvatar(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (file) emit('avatar', file)
}
</script>

<template>
  <SettingsSection title="账户" description="管理你的个人资料与账户访问。">
    <div class="settings-card profile-card">
      <div class="profile-card__top">
        <div class="profile-avatar" aria-label="当前头像">
          <img v-if="avatarUrl" :src="avatarUrl" alt="账户头像" />
          <UserRound v-else :size="34" :stroke-width="1.5" />
        </div>
        <div class="profile-card__identity"><span>PERSONAL ACCOUNT</span><strong>{{ profile.username }}</strong><small>{{ profile.email }}</small></div>
        <label class="profile-avatar-picker">
          <Camera :size="15" />更换头像
          <input type="file" accept="image/*" aria-label="更换头像" @change="onAvatar" />
        </label>
      </div>
      <div class="settings-field-grid profile-fields">
        <label class="settings-field"><span>用户名</span><Input :model-value="profile.username" aria-label="用户名" @update:model-value="update('username', $event)" /></label>
        <label class="settings-field"><span>邮箱</span><Input :model-value="profile.email" type="email" aria-label="邮箱" @update:model-value="update('email', $event)" /></label>
        <label class="settings-field"><span>时区</span><select :value="profile.timezone" @change="update('timezone', ($event.target as HTMLSelectElement).value)"><option v-for="timezone in timezoneOptions" :key="timezone" :value="timezone">{{ timezone }}</option></select></label>
        <label class="settings-field"><span>语言</span><select :value="profile.language" @change="update('language', ($event.target as HTMLSelectElement).value)"><option v-for="language in languageOptions" :key="language" :value="language">{{ language }}</option></select></label>
      </div>
    </div>
    <div class="settings-button-row">
      <ActionButton variant="secondary" @click="emit('password')"><KeyRound :size="15" />修改密码</ActionButton>
      <ActionButton variant="ghost" class="profile-logout" @click="emit('logout')"><LogOut :size="15" />退出登录</ActionButton>
    </div>
  </SettingsSection>
</template>

<style scoped>
.profile-card__top { display: flex; align-items: center; gap: 15px; min-width: 0; }
.profile-avatar { display: grid; width: 64px; height: 64px; flex: none; overflow: hidden; place-items: center; border: 2px solid rgba(255,255,255,.84); border-radius: 20px; color: #6e87d6; background: linear-gradient(145deg,#ecf4ff,#d9e1ff 70%,#e7dfff); box-shadow: 0 8px 18px rgba(65,89,151,.15); }
.profile-avatar img { width: 100%; height: 100%; object-fit: cover; }
.profile-card__identity { display: flex; flex-direction: column; min-width: 0; gap: 3px; }
.profile-card__identity span { color: #8796b1; font-size: 9px; font-weight: 760; letter-spacing: .13em; }
.profile-card__identity strong { color: var(--text-primary); font-size: 18px; font-weight: 730; }
.profile-card__identity small { overflow: hidden; color: var(--text-secondary); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.profile-avatar-picker { display: inline-flex; align-items: center; gap: 6px; flex: none; margin-left: auto; padding: 8px 10px; border: 1px solid rgba(150,172,214,.4); border-radius: 10px; color: #506a9a; background: rgba(255,255,255,.6); cursor: pointer; font-size: 11px; font-weight: 670; transition: transform .2s, background .2s; }
.profile-avatar-picker:hover { transform: translateY(-2px); background: rgba(255,255,255,.88); }
.profile-avatar-picker input { position: absolute; width: 1px; height: 1px; overflow: hidden; opacity: 0; }
.profile-fields { margin-top: 24px; padding-top: 19px; border-top: 1px solid var(--line); }
.profile-logout { color: #b86872 !important; }
@media (max-width: 560px) { .profile-card__top { flex-wrap: wrap; } .profile-avatar-picker { width: 100%; justify-content: center; margin: 4px 0 0; } }
</style>
