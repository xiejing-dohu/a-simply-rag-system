/** 前端应用入口文件

完成 Vue 3 实例创建、Pinia 状态库注册、Vue Router 路由挂载、
Element Plus UI 库及图标集中注册，并默认开启 Dark 暗黑主题模式。
*/

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import App from './App.vue'
import router from './router'
import './assets/styles/global.css'

// 强制开启系统 Dark 暗黑模式
document.documentElement.classList.add('dark')

const app = createApp(App)

// 集中注册 Element Plus 图标组件
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(createPinia())
app.use(router)
app.use(ElementPlus)

app.mount('#app')
