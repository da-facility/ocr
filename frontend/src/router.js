import { createRouter, createWebHistory } from 'vue-router'
import HomeView from './views/HomeView.vue'
import SessionView from './views/SessionView.vue'

const routes = [
  {
    path: '/',
    name: 'home',
    component: HomeView
  },
  {
    path: '/session/:id',
    name: 'session',
    component: SessionView
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
