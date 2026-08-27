<template>
  <div class="flex flex-col min-h-screen bg-sollium-dark text-slate-100 selection:bg-vectordrive selection:text-white">
    <Navbar />
    <main class="flex-grow">
      <router-view />
    </main>
    <Footer />
  </div>
</template>

<script setup>
import Navbar from './components/Navbar.vue'
import Footer from './components/Footer.vue'
</script>
