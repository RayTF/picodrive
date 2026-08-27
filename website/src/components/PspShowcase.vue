<template>
  <div class="flex flex-col items-center w-full max-w-4xl mx-auto">
    <!-- PSP Handheld Device with integrated SVG screen -->
    <div class="w-full max-w-3xl px-2 sm:px-0">
      <WhitePspSvg :slides="slides" :currentIndex="currentIndex" />
    </div>

    <!-- Interactive Screenshot Controls (Centered unified bar) -->
    <div class="mt-8 flex flex-col items-center gap-4 w-full max-w-2xl px-4">
      
      <!-- Unified Centered Pill Container -->
      <div class="flex flex-wrap items-center justify-center gap-1.5 sm:gap-2 p-1.5 rounded-2xl bg-sollium-dark-card border border-sollium-dark-border shadow-xl">
        
        <!-- Prev Arrow -->
        <button 
          @click="prevSlide" 
          type="button" 
          class="w-8 h-8 rounded-xl text-slate-400 hover:text-white hover:bg-sollium-dark-hover flex items-center justify-center transition-all cursor-pointer"
          aria-label="Previous screenshot"
          title="Previous screenshot"
        >
          <i class="fa-solid fa-chevron-left text-xs"></i>
        </button>

        <!-- Slide Selector Tabs -->
        <button 
          v-for="(slide, index) in slides" 
          :key="slide.id"
          @click="setSlide(index)"
          type="button"
          class="px-3.5 py-1.5 rounded-xl text-xs font-semibold transition-all flex items-center gap-2 cursor-pointer"
          :class="currentIndex === index 
            ? 'bg-vectordrive text-white shadow-glow-green' 
            : 'text-slate-400 hover:text-slate-200 hover:bg-sollium-dark-hover'"
        >
          <i :class="slide.icon" class="text-[11px]"></i>
          <span>{{ slide.title }}</span>
        </button>

        <!-- Next Arrow -->
        <button 
          @click="nextSlide" 
          type="button" 
          class="w-8 h-8 rounded-xl text-slate-400 hover:text-white hover:bg-sollium-dark-hover flex items-center justify-center transition-all cursor-pointer"
          aria-label="Next screenshot"
          title="Next screenshot"
        >
          <i class="fa-solid fa-chevron-right text-xs"></i>
        </button>

        <!-- Divider -->
        <div class="h-5 w-[1px] bg-sollium-dark-border mx-0.5 hidden sm:block"></div>

        <!-- Play / Pause Toggle -->
        <button 
          @click="toggleAutoplay"
          type="button"
          class="px-3 py-1.5 rounded-xl text-xs text-slate-400 hover:text-white hover:bg-sollium-dark-hover transition-all flex items-center gap-1.5 font-medium cursor-pointer"
          :title="isPlaying ? 'Pause slideshow' : 'Start slideshow'"
        >
          <i :class="isPlaying ? 'fa-solid fa-pause' : 'fa-solid fa-play'" class="text-[10px]"></i>
          <span>{{ isPlaying ? 'Auto' : 'Paused' }}</span>
        </button>

        <!-- Slide Index Counter -->
        <div class="px-2.5 py-1 rounded-lg bg-sollium-dark text-[11px] font-mono text-emerald-400 font-semibold border border-sollium-dark-border">
          {{ currentIndex + 1 }}/{{ slides.length }}
        </div>

      </div>

      <!-- Active Slide Description (Centered) -->
      <div class="text-center text-xs sm:text-sm text-slate-300 max-w-lg transition-all min-h-[36px] flex items-center justify-center">
        <p class="animate-fadeIn">
          <span class="font-bold text-white">{{ slides[currentIndex].title }}:</span>
          {{ slides[currentIndex].description }}
        </p>
      </div>

    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import WhitePspSvg from './WhitePsp.vue'

const slides = [
  {
    id: 'titlescreen',
    title: 'Title Screen',
    src: '/titlescreen.png',
    icon: 'fa-solid fa-gamepad',
    description: 'Polished nostalgic intro inspired by Sonic\'s UGC'
  },
  {
    id: 'mainmenu',
    title: 'Main Menu',
    src: '/mainmenu.png',
    icon: 'fa-solid fa-list-ul',
    description: 'UI featuring full artwork, descriptions and catalog browsing'
  },
  {
    id: 'pause',
    title: 'Pause Menu',
    src: '/pause.png',
    icon: 'fa-solid fa-sliders',
    description: 'Save states, button mapping, and configuration on the fly'
  }
]

const currentIndex = ref(0)
const isPlaying = ref(true)
let timer = null

const nextSlide = () => {
  currentIndex.value = (currentIndex.value + 1) % slides.length
}

const prevSlide = () => {
  currentIndex.value = (currentIndex.value - 1 + slides.length) % slides.length
}

const setSlide = (index) => {
  currentIndex.value = index
}

const startAutoplay = () => {
  if (timer) clearInterval(timer)
  timer = setInterval(() => {
    nextSlide()
  }, 4500)
  isPlaying.value = true
}

const stopAutoplay = () => {
  if (timer) clearInterval(timer)
  timer = null
  isPlaying.value = false
}

const toggleAutoplay = () => {
  if (isPlaying.value) {
    stopAutoplay()
  } else {
    startAutoplay()
  }
}

onMounted(() => {
  startAutoplay()
})

onUnmounted(() => {
  stopAutoplay()
})
</script>
