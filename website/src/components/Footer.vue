<template>
  <footer class="w-full bg-[#08090C] border-t border-sollium-dark-border mt-20 relative overflow-hidden">
    <!-- Top subtle accent line -->
    <div class="h-[2px] w-full bg-gradient-to-r from-transparent via-vectordrive to-transparent opacity-40"></div>
    
    <div class="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <div class="flex flex-col items-center justify-center text-center space-y-8">
        
        <!-- Brand & Badges -->
        <div class="flex flex-wrap items-center justify-center gap-6 sm:gap-10">
          <!-- Sollium Network -->
          <a 
            href="https://sollium.net" 
            target="_blank" 
            rel="noopener noreferrer"
            class="group flex items-center gap-3 px-4 py-2 rounded-xl bg-sollium-dark-card border border-sollium-dark-border hover:border-sollium-red/40 hover:bg-sollium-dark-surface transition-all"
          >
            <span class="text-xs text-slate-400 font-medium">Powered by</span>
            <img src="/network.svg" alt="The Sollium Network" class="h-6 w-auto object-contain group-hover:scale-105 transition-transform" />
            <span class="text-xs font-semibold text-slate-200 group-hover:text-sollium-red transition-colors">The Sollium Network</span>
          </a>
        </div>

        <!-- Quick Links -->
        <div class="flex flex-wrap items-center justify-center gap-x-8 gap-y-3 text-sm text-slate-400">
          <router-link to="/" class="hover:text-white transition-colors">Home</router-link>
          <router-link to="/download" class="hover:text-white transition-colors">Download</router-link>
          <a href="https://raysollium99.com/en/blog/vectordrive" target="_blank" rel="noopener noreferrer" class="hover:text-white transition-colors">The Story</a>
          <a href="https://ppsspp.org/" target="_blank" rel="noopener noreferrer" class="hover:text-white transition-colors">PPSSPP Emulator</a>
          <a href="https://github.com/RaySollium99/VectorDrive" target="_blank" rel="noopener noreferrer" class="hover:text-white transition-colors">GitHub</a>
        </div>

        <!-- Emulator Disclaimer & Legal Notice -->
        <div class="max-w-2xl text-xs text-slate-400 space-y-2 leading-relaxed">
          <p>
            VectorDrive is a completely independent homebrew project and is not affiliated with, endorsed by, or sponsored by Sony Computer Entertainment, SEGA Enterprises, or their subsidiaries.
          </p>
          <p>
            All SEGA trademarks, logos, and game titles are the property of SEGA Holdings Co., Ltd.
          </p>
          <p>
            PlayStation, PlayStation Portable and PSP are trademarks of Sony Interactive Entertainment Inc.
          </p>
          <p class="pt-2 text-slate-400">
            &copy; {{ new Date().getFullYear() }} VectorDrive. A project brought to you by the autism of <a href="https://raysollium99.com" class="text-sollium-red hover:underline font-medium">RaySollium99</a>.
          </p>
        </div>

      </div>
    </div>
  </footer>
</template>
