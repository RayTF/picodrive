<template>
  <div class="w-full space-y-24 sm:space-y-32">
    
    <!-- 1. HERO / CTA SECTION -->
    <section class="relative w-full min-h-[85vh] flex items-center justify-center pt-8 pb-16 px-4 overflow-hidden">
      <!-- VectorDrive Green Background with Overlay -->
      <div class="absolute inset-0 z-0">
        <img 
          src="/background.png" 
          alt="VectorDrive Green Background" 
          class="w-full h-full object-cover object-center opacity-35 scale-105"
        />
        <!-- Gradients to blend seamlessly into sollium-dark -->
        <div class="absolute inset-0 bg-gradient-to-b from-sollium-dark/60 via-sollium-dark/40 to-sollium-dark"></div>
        <div class="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(45,118,30,0.15)_0,transparent_70%)]"></div>
      </div>

      <!-- Hero Content (Centered) -->
      <div class="relative z-10 max-w-5xl mx-auto flex flex-col items-center text-center space-y-8">

        <!-- High-Res VectorDrive Logo -->
        <div class="w-full max-w-2xl px-4 animate-float">
          <img 
            src="/logo.png" 
            alt="VectorDrive" 
            class="w-full h-auto object-contain drop-shadow-[0_15px_35px_rgba(45,118,30,0.45)] max-h-[380px] sm:max-h-[480px] mx-auto"
          />
        </div>

        <!-- Tagline / Subtitle -->
        <p class="max-w-2xl text-base sm:text-xl text-slate-300 font-medium leading-relaxed">
          The definitive SEGA 8-bit and 16-bit experience on PSP
          <br />
          Skinned after the nostalgic Sonic's Ultimate Genesis Collection
        </p>

        <!-- CTA Action Buttons -->
        <div class="flex flex-col sm:flex-row items-center justify-center gap-4 w-full sm:w-auto pt-2">
          <router-link 
            to="/download" 
            class="btn-primary w-full sm:w-auto text-base px-8 py-4 text-center font-bold tracking-wide"
          >
            <i class="fa-solid fa-download text-lg"></i>
            <span>Download</span>
          </router-link>

          <a 
            href="https://github.com/RaySollium99/VectorDrive" 
            target="_blank" 
            rel="noopener noreferrer" 
            class="btn-secondary w-full sm:w-auto text-base px-7 py-4 text-center font-semibold"
          >
            <i class="fa-brands fa-github text-xl"></i>
            <span>GitHub</span>
          </a>
        </div>

        <!-- Supported Consoles Strip -->
        <div class="pt-6 flex flex-wrap items-center justify-center gap-2 sm:gap-4 text-xs font-semibold text-slate-400">
          <span class="px-3 py-1 rounded-md bg-sollium-dark-card/80 border border-sollium-dark-border">SEGA Genesis / Mega Drive</span>
          <span class="px-3 py-1 rounded-md bg-sollium-dark-card/80 border border-sollium-dark-border">SEGA Master System</span>
          <span class="px-3 py-1 rounded-md bg-sollium-dark-card/80 border border-sollium-dark-border">Game Gear</span>
          <span class="px-3 py-1 rounded-md bg-sollium-dark-card/80 border border-sollium-dark-border">SEGA CD</span>
          <span class="px-3 py-1 rounded-md bg-sollium-dark-card/80 border border-sollium-dark-border">SEGA 32X</span>
        </div>

      </div>
    </section>


    <!-- 2. EXPERIENCE SECTION (PSP Mockup with Carousel) -->
    <section class="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
      <div class="flex flex-col items-center text-center space-y-4 mb-10">
        <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-slate-800/60 border border-slate-700 text-xs text-slate-300 uppercase tracking-widest font-semibold">
          <i class="fa-solid fa-gamepad text-vectordrive"></i>
          <span>Experience</span>
        </div>
        <h2 class="text-3xl sm:text-4xl font-extrabold text-white tracking-tight">
          Handheld Nostalgia, Perfected
        </h2>
        <p class="text-slate-400 max-w-2xl text-sm sm:text-base">
          Experience smooth 60 FPS gameplay, the classic "Retro Dreams" soundtrack, and seamless save-state switching directly on your PSP hardware or PPSSPP emulator.
        </p>
      </div>

      <!-- PSP Device with Carousel -->
      <PspShowcase />
    </section>


    <!-- 3. NOSTALGIA SECTION (SEGA Blue Background with SUGC & SMDUC Logos) -->
    <section class="relative w-full py-20 px-4 overflow-hidden my-12 border-y border-sollium-dark-border">
      <!-- Background Image -->
      <div class="absolute inset-0 z-0">
        <img 
          src="/background_blue.png" 
          alt="SEGA Blue Background" 
          class="w-full h-full object-cover object-center opacity-40"
        />
        <div class="absolute inset-0 bg-gradient-to-r from-sollium-dark via-sega-blue-dark/50 to-sollium-dark"></div>
        <div class="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(24,65,145,0.25)_0,transparent_80%)]"></div>
      </div>

      <div class="relative z-10 max-w-5xl mx-auto flex flex-col items-center text-center space-y-10">
        
        <!-- Nostalgia Tag -->
        <div class="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-sega-blue/30 border border-sega-blue/60 text-sky-300 text-xs sm:text-sm font-semibold tracking-wide backdrop-blur-md shadow-glow-blue">
          <i class="fa-solid fa-compact-disc text-sky-400"></i>
          <span>Classic Interface Tribute</span>
        </div>

        <!-- SUGC & SMDUC Logos Side-by-Side -->
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-8 items-center justify-items-center w-full max-w-3xl">
          <!-- Sonic's Ultimate Genesis Collection Logo Card -->
          <div class="glass-card p-6 rounded-2xl border-sega-blue/40 w-full flex flex-col items-center justify-center space-y-4 hover:border-sega-blue transition-all group">
            <div class="h-28 flex items-center justify-center p-2">
              <img 
                src="/sugc_logo.png" 
                alt="Sonic's UGC Logo" 
                class="max-h-full w-auto object-contain group-hover:scale-128 transition-transform"
              />
            </div>
            <span class="text-xs font-bold uppercase tracking-wider text-sky-300">
              Sonic's Ultimate Genesis Collection
            </span>
          </div>

          <!-- SEGA Mega Drive Ultimate Collection Logo Card -->
          <div class="glass-card p-6 rounded-2xl border-sega-blue/40 w-full flex flex-col items-center justify-center space-y-4 hover:border-sega-blue transition-all group">
            <div class="h-28 flex items-center justify-center p-2">
              <img 
                src="/smduc_logo.png" 
                alt="SEGA MDUC Logo" 
                class="max-h-full w-auto object-contain group-hover:scale-128 transition-transform"
              />
            </div>
            <span class="text-xs font-bold uppercase tracking-wider text-sky-300">
              SEGA Mega Drive Ultimate Collection
            </span>
          </div>
        </div>

        <!-- Section Quote / Statement -->
        <div class="max-w-3xl space-y-4">
          <h3 class="text-2xl sm:text-3xl font-extrabold text-white leading-snug">
            Relive the classic Sonic's UGC and SEGA MDUC interface, now on your PSP!
          </h3>
          <p class="text-slate-300 text-sm sm:text-base leading-relaxed">
            Recreated with accuracy and the classic "Retro Dreams" soundtrack, VectorDrive brings back the golden era of seventh-generation SEGA collections, packed into a lightweight, portable launcher.
          </p>
        </div>

        <!-- Feature Grid in Nostalgia Section -->
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-6 w-full max-w-4xl pt-4 text-left">
          <div class="glass-card p-5 rounded-xl border-sollium-dark-border">
            <div class="w-10 h-10 rounded-lg bg-sega-blue/20 flex items-center justify-center text-sega-blue-light mb-3">
              <i class="fa-solid fa-layer-group"></i>
            </div>
            <h4 class="text-sm font-bold text-white mb-1">Authentic 2D UI</h4>
            <p class="text-xs text-slate-400">Faithful replica of the classic carousel cover-flow selection menu.</p>
          </div>

          <div class="glass-card p-5 rounded-xl border-sollium-dark-border">
            <div class="w-10 h-10 rounded-lg bg-sega-blue/20 flex items-center justify-center text-sega-blue-light mb-3">
              <i class="fa-solid fa-microchip"></i>
            </div>
            <h4 class="text-sm font-bold text-white mb-1">Based on PicoDrive</h4>
            <p class="text-xs text-slate-400">High-performance emulation engine compatible with the PSP</p>
          </div>

          <div class="glass-card p-5 rounded-xl border-sollium-dark-border">
            <div class="w-10 h-10 rounded-lg bg-sega-blue/20 flex items-center justify-center text-sega-blue-light mb-3">
              <i class="fa-solid fa-toolbox"></i>
            </div>
            <h4 class="text-sm font-bold text-white mb-1">VectorForge</h4>
            <p class="text-xs text-slate-400">Easily add custom ROMs, descriptions, box art, and create custom ZIP/ISO builds.</p>
          </div>
        </div>

      </div>
    </section>


    <!-- 4. THE STORY SECTION -->
    <section class="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
      <div class="glass-card rounded-3xl p-8 sm:p-12 border border-sollium-dark-border relative overflow-hidden">
        <!-- Subtle background glow -->
        <div class="absolute -right-16 -top-16 w-64 h-64 rounded-full bg-sollium-red/10 blur-3xl pointer-events-none"></div>

        <div class="flex flex-col md:flex-row items-center gap-8 sm:gap-12 relative z-10">
          
          <!-- Avatar -->
          <div class="flex-shrink-0 flex flex-col items-center">
            <div class="relative w-28 h-28 sm:w-36 sm:h-36 rounded-full overflow-hidden border-2 border-sollium-red shadow-glow-red p-1 bg-sollium-dark">
              <img 
                src="/raysollium99.png" 
                alt="RaySollium99" 
                class="w-full h-full rounded-full object-cover"
              />
            </div>
            <span class="mt-3 text-sm font-bold text-white">RaySollium99</span>
            <span class="text-xs text-sollium-red font-medium">Developer & Creator</span>
          </div>

          <!-- Story Text & Link -->
          <div class="space-y-4 text-center md:text-left">
            <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-sollium-red/10 border border-sollium-red/30 text-xs font-semibold text-sollium-red">
              <i class="fa-solid fa-heart"></i>
              <span>Behind the Project</span>
            </div>

            <h3 class="text-2xl sm:text-3xl font-extrabold text-white">
              The Story of VectorDrive
            </h3>

            <p class="text-sm sm:text-base text-slate-300 leading-relaxed">
              Growing up with Sonic's UGC on the Xbox 360 was what introduced me to emulation, and that helped mold me into who i am today, and that interface is highly nostalgic to me. After getting a PSP, i've wanted to have that interface on the go. VectorDrive is a passion project built to bring that exact presentation and nostalgic UI to the Sony PSP.
            </p>

            <div class="pt-2 flex flex-wrap items-center justify-center md:justify-start gap-4">
              <a 
                href="https://raysollium99.com/en/blog/vectordrive" 
                target="_blank" 
                rel="noopener noreferrer" 
                class="btn-red text-sm"
              >
                <i class="fa-solid fa-newspaper"></i>
                <span>Read Full Blogpost</span>
                <i class="fa-solid fa-arrow-up-right-from-square text-xs opacity-75"></i>
              </a>

              <a 
                href="https://raysollium99.com" 
                target="_blank" 
                rel="noopener noreferrer" 
                class="btn-secondary text-sm !py-2.5"
              >
                <span>Visit RaySollium99.com</span>
                <i class="fa-solid fa-globe text-xs text-slate-400"></i>
              </a>
            </div>
          </div>

        </div>
      </div>
    </section>

  </div>
</template>

<script setup>
import PspShowcase from '../components/PspShowcase.vue'
</script>
