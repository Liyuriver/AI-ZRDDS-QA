import { createApp } from 'vue'

import App from './App.vue'
import router from './router'
import { pinia } from './stores'
import { useUserStore } from './stores/user'
import './assets/styles/index.css'

const app = createApp(App)
useUserStore(pinia).restoreSession()

app.use(pinia)
app.use(router)

app.mount('#app')
