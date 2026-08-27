import { ViteSSG } from 'vite-ssg'
import App from './App.vue'
import './style.css'
import Home from './pages/Home.vue'
import Download from './pages/Download.vue'

const routes = [
  { 
    path: '/', 
    component: Home, 
    meta: { title: 'VectorDrive - SEGA Emulator for PSP' } 
  },
  { 
    path: '/download', 
    component: Download, 
    meta: { title: 'Download - VectorDrive' } 
  },
  { 
    path: '/:pathMatch(.*)*', 
    redirect: '/' 
  }
]

export const createApp = ViteSSG(
  App,
  { 
    routes, 
    scrollBehavior(to, from, savedPosition) {
      if (savedPosition) {
        return savedPosition
      }
      if (to.hash) {
        return { el: to.hash, behavior: 'smooth' }
      }
      return { top: 0, behavior: 'smooth' }
    }
  },
  ({ router, isClient }) => {
    if (isClient) {
      router.beforeEach((to, from, next) => {
        if (to.meta.title) {
          document.title = to.meta.title
        }
        next()
      })
    }
  }
)
