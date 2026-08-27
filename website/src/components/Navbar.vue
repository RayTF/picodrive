<template>
  <header class="sticky top-0 z-50 w-full backdrop-blur-xl bg-sollium-dark/85 border-b border-sollium-dark-border transition-all">
    <div class="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
      <div class="flex items-center justify-between h-16 sm:h-20">
        <!-- Logo & Brand -->
        <router-link to="/" class="flex items-center gap-3 group">
          <div class="relative w-10 h-10 rounded-xl overflow-hidden shadow-glow-green/40 group-hover:scale-105 transition-transform">
            <img src="/icon.png" alt="VectorDrive Icon" class="w-full h-full object-contain" />
          </div>
          <div class="flex flex-col">
            <span class="font-extrabold text-xl tracking-wide text-white group-hover:text-vectordrive transition-colors font-sans">
              VectorDrive
            </span>
            <span class="text-[10px] uppercase font-semibold tracking-wider text-emerald-500/80 -mt-1">
              SEGA PSP Emulator
            </span>
          </div>
        </router-link>

        <!-- Desktop Navigation Links (Centered) -->
        <nav class="hidden md:flex items-center gap-1 sm:gap-2 bg-sollium-dark-card/90 px-3 py-1.5 rounded-full border border-sollium-dark-border shadow-inner">
          <router-link 
            to="/" 
            class="px-4 py-2 rounded-full text-sm font-medium transition-all text-slate-300 hover:text-white hover:bg-sollium-dark-hover"
            active-class="!text-white !bg-vectordrive/20 !border-vectordrive/40 border text-vectordrive font-semibold shadow-glow-green"
          >
            <i class="fa-solid fa-house mr-1.5 text-xs opacity-75"></i>
            Home
          </router-link>

          <router-link 
            to="/download" 
            class="px-4 py-2 rounded-full text-sm font-medium transition-all text-slate-300 hover:text-white hover:bg-sollium-dark-hover"
            active-class="!text-white !bg-vectordrive/20 !border-vectordrive/40 border text-vectordrive font-semibold shadow-glow-green"
          >
            <i class="fa-solid fa-download mr-1.5 text-xs opacity-75"></i>
            Download
          </router-link>

          <a 
            href="https://raysollium99.com/en/blog/vectordrive" 
            target="_blank"
            rel="noopener noreferrer"
            class="px-4 py-2 rounded-full text-sm font-medium transition-all text-slate-300 hover:text-white hover:bg-sollium-dark-hover flex items-center"
          >
            <i class="fa-solid fa-book-open mr-1.5 text-xs opacity-75"></i>
            The Story
          </a>
        </nav>

        <!-- Right Side CTA / Links -->
        <div class="hidden md:flex items-center gap-3">
          <a 
            href="https://github.com/RaySollium99/VectorDrive" 
            target="_blank" 
            rel="noopener noreferrer" 
            class="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold bg-sollium-dark-card hover:bg-sollium-dark-hover border border-sollium-dark-border text-slate-200 hover:text-white transition-all hover:border-slate-600"
            title="GitHub Repository"
          >
            <i class="fa-brands fa-github text-base"></i>
            <span>GitHub</span>
          </a>

          <router-link 
            to="/download" 
            class="btn-primary !px-4 !py-2 text-sm !rounded-xl"
          >
            <i class="fa-solid fa-cloud-arrow-down text-xs"></i>
            <span>Get VectorDrive</span>
          </router-link>
        </div>

        <!-- Mobile Menu Button -->
        <div class="md:hidden flex items-center">
          <button 
            @click="mobileMenuOpen = !mobileMenuOpen" 
            type="button" 
            class="p-2 rounded-lg bg-sollium-dark-card border border-sollium-dark-border text-slate-300 hover:text-white"
            aria-label="Toggle navigation menu"
          >
            <i :class="mobileMenuOpen ? 'fa-solid fa-xmark' : 'fa-solid fa-bars'" class="text-lg w-6 h-6 flex items-center justify-center"></i>
          </button>
        </div>
      </div>
    </div>

    <!-- Mobile Menu Dropdown -->
    <div v-show="mobileMenuOpen" class="md:hidden border-t border-sollium-dark-border bg-sollium-dark/95 backdrop-blur-2xl px-4 pt-3 pb-5 space-y-2">
      <router-link 
        to="/" 
        @click="mobileMenuOpen = false" 
        class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-slate-200 hover:bg-sollium-dark-hover hover:text-white"
        active-class="!bg-vectordrive/20 !text-emerald-400 font-semibold"
      >
        <i class="fa-solid fa-house w-5 text-center"></i>
        <span>Home</span>
      </router-link>
      <router-link 
        to="/download" 
        @click="mobileMenuOpen = false" 
        class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-slate-200 hover:bg-sollium-dark-hover hover:text-white"
        active-class="!bg-vectordrive/20 !text-emerald-400 font-semibold"
      >
        <i class="fa-solid fa-download w-5 text-center"></i>
        <span>Download</span>
      </router-link>
      <a 
        href="https://raysollium99.com/en/blog/vectordrive" 
        target="_blank"
        rel="noopener noreferrer"
        class="flex items-center justify-between px-3 py-2.5 rounded-lg text-slate-200 hover:bg-sollium-dark-hover hover:text-white"
      >
        <span class="flex items-center gap-3">
          <i class="fa-solid fa-book-open w-5 text-center"></i>
          <span>The Story</span>
        </span>
      </a>
      <a 
        href="https://github.com/RaySollium99/VectorDrive" 
        target="_blank"
        rel="noopener noreferrer"
        class="flex items-center justify-between px-3 py-2.5 rounded-lg text-slate-200 hover:bg-sollium-dark-hover hover:text-white"
      >
        <span class="flex items-center gap-3">
          <i class="fa-brands fa-github w-5 text-center"></i>
          <span>GitHub Source</span>
        </span>
        <i class="fa-solid fa-arrow-up-right-from-square text-xs opacity-60"></i>
      </a>
      <div class="pt-2">
        <router-link 
          to="/download" 
          @click="mobileMenuOpen = false" 
          class="btn-primary w-full text-center"
        >
          <i class="fa-solid fa-cloud-arrow-down"></i>
          <span>Download Now</span>
        </router-link>
      </div>
    </div>
  </header>
</template>

<script setup>
import { ref } from 'vue'

const mobileMenuOpen = ref(false)
</script>
