<template>
  <div class="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8 sm:py-12 space-y-16">
    
    <!-- Page Header (Centered) -->
    <div class="flex flex-col items-center text-center space-y-4 max-w-3xl mx-auto">
      <div class="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-vectordrive/20 border border-vectordrive/40 text-emerald-400 text-xs sm:text-sm font-semibold tracking-wide shadow-glow-green">
        <i class="fa-solid fa-cloud-arrow-down"></i>
        <span>Official VectorDrive Downloads</span>
      </div>
      <h1 class="text-3xl sm:text-5xl font-black text-white tracking-tight">
        Download VectorDrive
      </h1>
      <p class="text-slate-300 text-sm sm:text-base leading-relaxed">
        Choose your preferred edition, theme variant, and package format for your PSP or emulator below.
      </p>
    </div>

    <!-- 1. DYNAMIC SELECTOR SECTION -->
    <div class="glass-card rounded-3xl p-6 sm:p-10 border border-sollium-dark-border shadow-2xl relative overflow-hidden">
      <div class="absolute -right-20 -bottom-20 w-80 h-80 rounded-full bg-vectordrive/10 blur-3xl pointer-events-none"></div>

      <div class="relative z-10 space-y-10">
        
        <!-- Step Indicator & Header -->
        <div class="flex items-center justify-between border-b border-sollium-dark-border pb-6">
          <div class="flex items-center gap-3">
            <div class="w-10 h-10 rounded-xl bg-vectordrive/20 border border-vectordrive/40 flex items-center justify-center text-vectordrive font-bold">
              1
            </div>
            <div>
              <h2 class="text-lg sm:text-xl font-extrabold text-white">Custom Package Selector</h2>
              <p class="text-xs text-slate-400">Configure edition and target format</p>
            </div>
          </div>

          <span class="text-xs font-mono text-emerald-400 bg-vectordrive/10 px-3 py-1 rounded-full border border-vectordrive/30">
            Ready
          </span>
        </div>

        <!-- Selection Grid: Step 1 Variant & Step 2 Version -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
          
          <!-- Step 1: Pick Variant -->
          <div class="space-y-4">
            <label class="block text-sm font-bold uppercase tracking-wider text-slate-300 flex items-center gap-2">
              <span class="w-6 h-6 rounded-full bg-slate-800 text-slate-300 text-xs flex items-center justify-center font-bold">A</span>
              Select Theme & Variant
            </label>

            <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <button
                v-for="variant in variants"
                :key="variant.id"
                @click="selectedVariant = variant.id"
                type="button"
                class="flex flex-col items-center text-center p-4 rounded-2xl border transition-all cursor-pointer relative"
                :class="selectedVariant === variant.id
                  ? 'bg-vectordrive/20 border-vectordrive text-white shadow-glow-green'
                  : 'bg-sollium-dark-card border-sollium-dark-border text-slate-400 hover:border-slate-600 hover:text-slate-200'"
              >
                <div class="w-8 h-8 rounded-lg flex items-center justify-center mb-2" :class="variant.bgClass">
                  <i :class="variant.icon" class="text-sm"></i>
                </div>
                <span class="text-sm font-bold text-slate-100">{{ variant.name }}</span>
                <span class="text-[11px] text-slate-400 mt-1">{{ variant.tag }}</span>

                <div v-if="selectedVariant === variant.id" class="absolute top-2 right-2 text-emerald-400">
                  <i class="fa-solid fa-circle-check text-xs"></i>
                </div>
              </button>
            </div>
          </div>

          <!-- Step 2: Pick Version / Format -->
          <div class="space-y-4">
            <label class="block text-sm font-bold uppercase tracking-wider text-slate-300 flex items-center gap-2">
              <span class="w-6 h-6 rounded-full bg-slate-800 text-slate-300 text-xs flex items-center justify-center font-bold">B</span>
              Select Target Format
            </label>

            <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <button
                v-for="format in formats"
                :key="format.id"
                @click="selectedFormat = format.id"
                type="button"
                class="flex flex-col items-center text-center p-4 rounded-2xl border transition-all cursor-pointer relative"
                :class="selectedFormat === format.id
                  ? 'bg-vectordrive/20 border-vectordrive text-white shadow-glow-green'
                  : 'bg-sollium-dark-card border-sollium-dark-border text-slate-400 hover:border-slate-600 hover:text-slate-200'"
              >
                <div class="w-8 h-8 rounded-lg flex items-center justify-center mb-2 bg-slate-800 text-slate-300">
                  <i :class="format.icon" class="text-sm"></i>
                </div>
                <span class="text-sm font-bold text-slate-100">{{ format.name }}</span>
                <span class="text-[11px] text-slate-400 mt-1">{{ format.tag }}</span>

                <div v-if="selectedFormat === format.id" class="absolute top-2 right-2 text-emerald-400">
                  <i class="fa-solid fa-circle-check text-xs"></i>
                </div>
              </button>
            </div>
          </div>

        </div>

        <!-- Download Action Card & Dynamic Result -->
        <div class="bg-sollium-dark/80 rounded-2xl p-6 sm:p-8 border border-sollium-dark-border flex flex-col md:flex-row items-center justify-between gap-6">
          <div class="space-y-2 text-center md:text-left">
            <div class="flex flex-wrap items-center justify-center md:justify-start gap-2">
              <span class="px-2.5 py-0.5 rounded-md bg-vectordrive/20 text-emerald-400 text-xs font-semibold border border-vectordrive/30">
                {{ activeVariantObj.name }}
              </span>
              <span class="px-2.5 py-0.5 rounded-md bg-slate-800 text-slate-300 text-xs font-semibold border border-slate-700">
                {{ activeFormatObj.name }}
              </span>
              <span class="text-xs font-mono text-slate-400">
                Size: ~{{ currentDownload.size }}
              </span>
            </div>

            <h3 class="text-lg font-bold text-white flex items-center justify-center md:justify-start gap-2">
              <i class="fa-solid fa-file-zipper text-vectordrive"></i>
              <span>{{ currentDownload.filename }}</span>
            </h3>
            <p class="text-xs text-slate-400 max-w-xl">
              {{ currentDownload.description }}
            </p>
          </div>

          <!-- Download Button -->
          <div class="flex flex-col items-center sm:items-end w-full md:w-auto">
            <a 
              :href="currentDownload.url" 
              :download="currentDownload.filename"
              @click="onDownloadClicked"
              class="btn-primary w-full sm:w-auto text-base px-8 py-4 !rounded-2xl text-center flex items-center justify-center gap-3 font-bold"
            >
              <i class="fa-solid fa-download text-lg"></i>
              <span>Download File</span>
            </a>
            <span class="text-[11px] text-slate-400 mt-2">Direct HTTP Download</span>
          </div>
        </div>

        <!-- Inline Instructions (Contextual to the selected format) -->
        <div class="bg-sollium-dark-surface/50 rounded-2xl p-6 border border-sollium-dark-border space-y-3">
          <h4 class="text-sm font-bold text-white flex items-center gap-2">
            <i class="fa-solid fa-circle-info text-vectordrive"></i>
            <span>Quick Installation Guide for {{ activeFormatObj.name }}</span>
          </h4>
          
          <!-- Memory Stick Instructions -->
          <ol v-if="selectedFormat === 'memorystick'" class="list-decimal list-inside text-xs sm:text-sm text-slate-300 space-y-2 leading-relaxed">
            <li>Extract the downloaded <code class="text-emerald-400 bg-sollium-dark px-1.5 py-0.5 rounded font-mono">VectorDrive.zip</code> archive.</li>
            <li>Connect your PSP via USB or insert your Memory Stick into your PC.</li>
            <li>Copy the extracted <code class="text-emerald-400 bg-sollium-dark px-1.5 py-0.5 rounded font-mono">VectorDrive</code> folder into <code class="text-emerald-400 bg-sollium-dark px-1.5 py-0.5 rounded font-mono">ms0:/PSP/GAME/</code>.</li>
            <li>Disconnect and launch VectorDrive from the PSP XMB <span class="font-semibold text-white">Game &gt; Memory Stick</span> menu!</li>
          </ol>

          <!-- ISO Instructions -->
          <ol v-if="selectedFormat === 'iso'" class="list-decimal list-inside text-xs sm:text-sm text-slate-300 space-y-2 leading-relaxed">
            <li>Download the <code class="text-sky-300 bg-sollium-dark px-1.5 py-0.5 rounded font-mono">.iso</code> image file directly.</li>
            <li><span class="font-semibold text-white">For Real PSP Hardware:</span> Copy the <code class="text-sky-300 bg-sollium-dark px-1.5 py-0.5 rounded font-mono">.iso</code> to the <code class="text-sky-300 bg-sollium-dark px-1.5 py-0.5 rounded font-mono">ms0:/ISO/</code> directory on your memory card root.</li>
            <li><span class="font-semibold text-white">For PPSSPP Emulator:</span> Open <a href="https://ppsspp.org/" target="_blank" class="text-sky-400 hover:underline">PPSSPP</a>, click "Browse", and select the <code class="text-sky-300 bg-sollium-dark px-1.5 py-0.5 rounded font-mono">.iso</code> file to boot directly.</li>
          </ol>

          <!-- NoROM Instructions -->
          <ol v-if="selectedFormat === 'norom'" class="list-decimal list-inside text-xs sm:text-sm text-slate-300 space-y-2 leading-relaxed">
            <li>Download your preferred <code class="text-sollium-red bg-sollium-dark px-1.5 py-0.5 rounded font-mono">NoROM Edition</code> variant, and download <span class="font-semibold text-white">VectorForge</span> below.</li>
            <li>Launch VectorForge, click <span class="font-semibold text-white">"Add Folder"</span>, select your SEGA ROM directory, and pick library (<code class="text-sollium-red bg-sollium-dark px-1.5 py-0.5 rounded font-mono">main</code> / <code class="text-sollium-red bg-sollium-dark px-1.5 py-0.5 rounded font-mono">extra</code>).</li>
            <li>Click <span class="font-semibold text-white">"Scrape"</span> with your <a href="https://screenscraper.fr" target="_blank" class="text-emerald-400 hover:underline">ScreenScraper.fr</a> account to fetch artwork and descriptions.</li>
            <li>Under <span class="font-semibold text-white">"Builder"</span>, select the downloaded NoROM ZIP, then click <span class="font-semibold text-white">"Build ZIP"</span> or <span class="font-semibold text-white">"Build ISO"</span>.</li>
            <li>Copy the generated build to your PSP (<code class="text-emerald-400 bg-sollium-dark px-1.5 py-0.5 rounded font-mono">ms0:/PSP/GAME/</code> or <code class="text-sky-300 bg-sollium-dark px-1.5 py-0.5 rounded font-mono">ms0:/ISO/</code>) and launch from XMB!</li>
          </ol>
        </div>

      </div>
    </div>


    <!-- 2. VECTORFORGE COMPANION APP SECTION -->
    <div class="glass-card rounded-3xl p-6 sm:p-10 border border-sollium-dark-border shadow-2xl relative overflow-hidden">
      <div class="flex flex-col md:flex-row items-center justify-between gap-8">
        
        <div class="flex items-start gap-5 max-w-xl">
          <div class="w-16 h-16 sm:w-20 sm:h-20 rounded-2xl bg-sollium-dark-card border border-sollium-dark-border p-3 flex-shrink-0 shadow-glow-green/30">
            <img src="/icon.png" alt="VectorForge Icon" class="w-full h-full object-contain" />
          </div>

          <div class="space-y-2">
            <div class="inline-flex items-center gap-2 px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 text-xs font-semibold border border-emerald-500/20">
              Desktop Companion Tool
            </div>
            <h2 class="text-2xl font-extrabold text-white">VectorForge</h2>
            <p class="text-xs sm:text-sm text-slate-300 leading-relaxed">
              VectorForge is the official desktop tool for managing your VectorDrive library, adding custom box art, scraping ScreenScraper metadata, and compiling custom ZIP/ISO images.
            </p>
          </div>
        </div>

        <!-- Download Buttons for Windows & Linux -->
        <div class="flex flex-col sm:flex-row md:flex-col lg:flex-row gap-3 w-full md:w-auto">
          <!-- Windows -->
          <a 
            href="/files/VectorForge.exe" 
            download="VectorForge.exe"
            class="btn-secondary !px-5 !py-3 rounded-xl flex items-center justify-center gap-3 text-sm font-bold hover:border-sky-500"
          >
            <i class="fa-brands fa-windows text-sky-400 text-base"></i>
            <div class="text-left">
              <div class="leading-none text-white">Windows (x64)</div>
              <div class="text-[10px] text-slate-400 font-mono mt-0.5">.exe (~56.0 MB)</div>
            </div>
          </a>

          <!-- Linux -->
          <a 
            href="/files/VectorForge.AppImage" 
            download="VectorForge.AppImage"
            class="btn-secondary !px-5 !py-3 rounded-xl flex items-center justify-center gap-3 text-sm font-bold hover:border-amber-500"
          >
            <i class="fa-brands fa-linux text-amber-400 text-base"></i>
            <div class="text-left">
              <div class="leading-none text-white">Linux AppImage</div>
              <div class="text-[10px] text-slate-400 font-mono mt-0.5">.AppImage (~79.3 MB)</div>
            </div>
          </a>
        </div>

      </div>
    </div>


    <!-- 3. DETAILED INSTRUCTIONS SECTION (Consistent 3-Card Grid) -->
    <div class="space-y-8">
      <div class="text-center space-y-2 max-w-2xl mx-auto">
        <h2 class="text-2xl sm:text-3xl font-extrabold text-white">Installation & Setup Guide</h2>
        <p class="text-xs sm:text-sm text-slate-400">
          Comprehensive step-by-step instructions for real PSP/PS Vita hardware, PPSSPP emulator, and custom VectorForge builds.
        </p>
      </div>

      <!-- Instruction Cards Grid (Consistent Layout) -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 items-stretch">
        
        <!-- Card 1: Memory Stick (Pre-built) -->
        <div class="glass-card p-6 sm:p-7 rounded-3xl border border-sollium-dark-border flex flex-col justify-between h-full hover:border-vectordrive/50 transition-all duration-300 group">
          <div>
            <!-- Top Icon & Badge -->
            <div class="flex items-center justify-between mb-4">
              <div class="w-12 h-12 rounded-2xl bg-vectordrive/20 border border-vectordrive/30 text-emerald-400 flex items-center justify-center text-xl shadow-glow-green/20">
                <i class="fa-solid fa-sd-card"></i>
              </div>
              <span class="text-[11px] font-semibold px-2.5 py-1 rounded-full bg-vectordrive/10 text-emerald-400 border border-vectordrive/30">
                Pre-built
              </span>
            </div>

            <!-- Card Title & Subtitle -->
            <h3 class="text-xl font-black text-white group-hover:text-emerald-400 transition-colors">
              Memory Stick
            </h3>
            <p class="text-xs text-slate-400 mt-1 mb-4 leading-relaxed min-h-[34px]">
              For PSP 1000, 2000, 3000, Go, Street, or PS Vita with Custom Firmware (PRO / ME / ARK).
            </p>

            <div class="h-[1px] w-full bg-sollium-dark-border mb-4"></div>

            <!-- Step List -->
            <ol class="text-xs text-slate-300 space-y-3 leading-relaxed">
              <li class="flex items-start gap-2.5">
                <span class="w-5 h-5 rounded-full bg-sollium-dark border border-sollium-dark-border text-emerald-400 text-[11px] font-bold flex items-center justify-center flex-shrink-0 mt-0.5">1</span>
                <span>Select your preferred variant and download the <code class="text-emerald-400 font-mono">VectorDrive.zip</code> archive.</span>
              </li>
              <li class="flex items-start gap-2.5">
                <span class="w-5 h-5 rounded-full bg-sollium-dark border border-sollium-dark-border text-emerald-400 text-[11px] font-bold flex items-center justify-center flex-shrink-0 mt-0.5">2</span>
                <span>Extract the ZIP folder onto your computer.</span>
              </li>
              <li class="flex items-start gap-2.5">
                <span class="w-5 h-5 rounded-full bg-sollium-dark border border-sollium-dark-border text-emerald-400 text-[11px] font-bold flex items-center justify-center flex-shrink-0 mt-0.5">3</span>
                <span>Copy the extracted <code class="text-emerald-400 font-mono">VectorDrive</code> folder into <code class="text-emerald-400 font-mono">ms0:/PSP/GAME/</code> on your Memory Stick.</span>
              </li>
              <li class="flex items-start gap-2.5">
                <span class="w-5 h-5 rounded-full bg-sollium-dark border border-sollium-dark-border text-emerald-400 text-[11px] font-bold flex items-center justify-center flex-shrink-0 mt-0.5">4</span>
                <span>Disconnect PSP and launch VectorDrive from the XMB <span class="text-white font-semibold">Game &gt; Memory Stick</span> menu!</span>
              </li>
            </ol>
          </div>
        </div>

        <!-- Card 2: ISO Disc Image -->
        <div class="glass-card p-6 sm:p-7 rounded-3xl border border-sollium-dark-border flex flex-col justify-between h-full hover:border-sega-blue/60 transition-all duration-300 group">
          <div>
            <!-- Top Icon & Badge -->
            <div class="flex items-center justify-between mb-4">
              <div class="w-12 h-12 rounded-2xl bg-sega-blue/20 border border-sega-blue/40 text-sky-400 flex items-center justify-center text-xl shadow-glow-blue/20">
                <i class="fa-solid fa-compact-disc"></i>
              </div>
              <span class="text-[11px] font-semibold px-2.5 py-1 rounded-full bg-sega-blue/10 text-sky-400 border border-sega-blue/30">
                Emulator & CFW
              </span>
            </div>

            <!-- Card Title & Subtitle -->
            <h3 class="text-xl font-black text-white group-hover:text-sky-400 transition-colors">
              ISO Disc Image
            </h3>
            <p class="text-xs text-slate-400 mt-1 mb-4 leading-relaxed min-h-[34px]">
              Bootable disc image for PPSSPP emulator on PC/Android/iOS/Deck or CFW PSP ISO loaders.
            </p>

            <div class="h-[1px] w-full bg-sollium-dark-border mb-4"></div>

            <!-- Step List -->
            <ol class="text-xs text-slate-300 space-y-3 leading-relaxed">
              <li class="flex items-start gap-2.5">
                <span class="w-5 h-5 rounded-full bg-sollium-dark border border-sollium-dark-border text-sky-400 text-[11px] font-bold flex items-center justify-center flex-shrink-0 mt-0.5">1</span>
                <span>Select your preferred variant and download the <code class="text-sky-300 font-mono">.iso</code> image file directly.</span>
              </li>
              <li class="flex items-start gap-2.5">
                <span class="w-5 h-5 rounded-full bg-sollium-dark border border-sollium-dark-border text-sky-400 text-[11px] font-bold flex items-center justify-center flex-shrink-0 mt-0.5">2</span>
                <span><span class="text-white font-semibold">For Real PSP:</span> Transfer the <code class="text-sky-300 font-mono">.iso</code> into the <code class="text-sky-300 font-mono">ms0:/ISO/</code> folder.</span>
              </li>
              <li class="flex items-start gap-2.5">
                <span class="w-5 h-5 rounded-full bg-sollium-dark border border-sollium-dark-border text-sky-400 text-[11px] font-bold flex items-center justify-center flex-shrink-0 mt-0.5">3</span>
                <span><span class="text-white font-semibold">For PPSSPP:</span> Open <a href="https://ppsspp.org/" target="_blank" class="text-sky-400 hover:underline">PPSSPP</a>, browse to the ISO, and launch to play with upscaling.</span>
              </li>
              <li class="flex items-start gap-2.5">
                <span class="w-5 h-5 rounded-full bg-sollium-dark border border-sollium-dark-border text-sky-400 text-[11px] font-bold flex items-center justify-center flex-shrink-0 mt-0.5">4</span>
                <span>Enjoy 60 FPS gameplay, custom filters, and save-state switching!</span>
              </li>
            </ol>
          </div>
        </div>

        <!-- Card 3: Custom Version via VectorForge -->
        <div class="glass-card p-6 sm:p-7 rounded-3xl border border-sollium-dark-border flex flex-col justify-between h-full hover:border-sollium-red/60 transition-all duration-300 group">
          <div>
            <!-- Top Icon & Badge -->
            <div class="flex items-center justify-between mb-4">
              <div class="w-12 h-12 rounded-2xl bg-sollium-red/20 border border-sollium-red/40 text-sollium-red flex items-center justify-center text-xl shadow-glow-red/20">
                <i class="fa-solid fa-wrench"></i>
              </div>
              <span class="text-[11px] font-semibold px-2.5 py-1 rounded-full bg-sollium-red/10 text-sollium-red border border-sollium-red/30">
                VectorForge
              </span>
            </div>

            <!-- Card Title & Subtitle -->
            <h3 class="text-xl font-black text-white group-hover:text-sollium-red transition-colors">
              Custom (No ROMs)
            </h3>
            <p class="text-xs text-slate-400 mt-1 mb-4 leading-relaxed min-h-[34px]">
              Build custom compilations with your own ROMs, scraped box art, and metadata.
            </p>

            <div class="h-[1px] w-full bg-sollium-dark-border mb-4"></div>

            <!-- Step List -->
            <ol class="text-xs text-slate-300 space-y-3 leading-relaxed">
              <li class="flex items-start gap-2.5">
                <span class="w-5 h-5 rounded-full bg-sollium-dark border border-sollium-dark-border text-sollium-red text-[11px] font-bold flex items-center justify-center flex-shrink-0 mt-0.5">1</span>
                <span>Download the <span class="text-white font-semibold">NoROM Edition</span> and get <span class="text-white font-semibold">VectorForge</span> below.</span>
              </li>
              <li class="flex items-start gap-2.5">
                <span class="w-5 h-5 rounded-full bg-sollium-dark border border-sollium-dark-border text-sollium-red text-[11px] font-bold flex items-center justify-center flex-shrink-0 mt-0.5">2</span>
                <span>Open VectorForge, click <span class="text-white font-semibold">"Add Folder"</span> with your ROMs, and choose library (<code class="text-sollium-red font-mono">main</code>/<code class="text-sollium-red font-mono">extra</code>).</span>
              </li>
              <li class="flex items-start gap-2.5">
                <span class="w-5 h-5 rounded-full bg-sollium-dark border border-sollium-dark-border text-sollium-red text-[11px] font-bold flex items-center justify-center flex-shrink-0 mt-0.5">3</span>
                <span>Click <span class="text-white font-semibold">"Scrape"</span> with your <a href="https://screenscraper.fr" target="_blank" class="text-emerald-400 hover:underline">ScreenScraper.fr</a> login to fetch box art and info.</span>
              </li>
              <li class="flex items-start gap-2.5">
                <span class="w-5 h-5 rounded-full bg-sollium-dark border border-sollium-dark-border text-sollium-red text-[11px] font-bold flex items-center justify-center flex-shrink-0 mt-0.5">4</span>
                <span>Go to <span class="text-white font-semibold">"Builder"</span>, select your NoROM ZIP, and click <span class="text-white font-semibold">"Build ZIP"</span> or <span class="text-white font-semibold">"Build ISO"</span>!</span>
              </li>
            </ol>
          </div>
        </div>

      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const variants = [
  { 
    id: 'base', 
    name: 'VectorDrive', 
    tag: 'Custom-made VectorDrive theme', 
    icon: 'fa-solid fa-gamepad',
    bgClass: 'bg-vectordrive/20 text-emerald-400' 
  },
  { 
    id: 'sugc', 
    name: "Sonic's UGC", 
    tag: 'Remaster of US Sonic\'s UGC theme', 
    icon: 'fa-solid fa-bolt',
    bgClass: 'bg-sky-600/20 text-sky-400' 
  },
  { 
    id: 'smduc', 
    name: 'SEGA MDUC', 
    tag: 'Remaster of Europe SEGA MDUC theme', 
    icon: 'fa-solid fa-dragon',
    bgClass: 'bg-blue-600/20 text-blue-400' 
  },
]

const formats = [
  { 
    id: 'memorystick', 
    name: 'Memory Stick', 
    tag: 'Ready-to-play with preloaded games', 
    icon: 'fa-solid fa-sd-card' 
  },
  { 
    id: 'iso', 
    name: 'ISO Image', 
    tag: 'For PPSSPP emulation or PSP/Vita CFW', 
    icon: 'fa-solid fa-compact-disc' 
  },
  { 
    id: 'norom', 
    name: 'NoROM Edition', 
    tag: 'Custom ROMs via VectorForge', 
    icon: 'fa-solid fa-folder-open' 
  },
]

const selectedVariant = ref('base')
const selectedFormat = ref('memorystick')

const activeVariantObj = computed(() => {
  return variants.find(v => v.id === selectedVariant.value) || variants[0]
})

const activeFormatObj = computed(() => {
  return formats.find(f => f.id === selectedFormat.value) || formats[0]
})

// Map selections to the actual download files in public/files/
const downloadMap = {
  'base-memorystick': {
    filename: 'VectorDrive.zip',
    url: '/files/Memory Stick/VectorDrive.zip',
    size: '41.9 MB',
    description: 'Complete Memory Stick package with custom VectorDrive theme and included game library.'
  },
  'sugc-memorystick': {
    filename: 'VectorDrive SUGC.zip',
    url: '/files/Memory Stick/VectorDrive SUGC.zip',
    size: '42.0 MB',
    description: 'Sonic\'s Ultimate Genesis Collection themed Memory Stick edition.'
  },
  'smduc-memorystick': {
    filename: 'VectorDrive SMDUC.zip',
    url: '/files/Memory Stick/VectorDrive SMDUC.zip',
    size: '43.8 MB',
    description: 'SEGA Mega Drive Ultimate Collection themed Memory Stick edition.'
  },
  'base-iso': {
    filename: 'VectorDrive.iso',
    url: '/files/ISO/VectorDrive.iso',
    size: '71.9 MB',
    description: 'Bootable ISO disc image formatted for PPSSPP emulator and real PSP CFW loaders.'
  },
  'sugc-iso': {
    filename: 'VectorDrive SUGC.iso',
    url: '/files/ISO/VectorDrive SUGC.iso',
    size: '72.0 MB',
    description: 'Bootable Sonic\'s UGC themed ISO disc image.'
  },
  'smduc-iso': {
    filename: 'VectorDrive SMDUC.iso',
    url: '/files/ISO/VectorDrive SMDUC.iso',
    size: '75.1 MB',
    description: 'Bootable SEGA MDUC themed ISO disc image.'
  },
  'base-norom': {
    filename: 'VectorDrive.zip',
    url: '/files/NoROM/VectorDrive.zip',
    size: '4.4 MB',
    description: 'Ultra-lightweight clean launcher package for building with VectorForge.'
  },
  'sugc-norom': {
    filename: 'VectorDrive SUGC.zip',
    url: '/files/NoROM/VectorDrive SUGC.zip',
    size: '4.4 MB',
    description: 'Clean Sonic\'s UGC themed package for building with VectorForge.'
  },
  'smduc-norom': {
    filename: 'VectorDrive SMDUC.zip',
    url: '/files/NoROM/VectorDrive SMDUC.zip',
    size: '4.4 MB',
    description: 'Clean SEGA MDUC themed package for building with VectorForge.'
  }
}

const currentDownload = computed(() => {
  const key = `${selectedVariant.value}-${selectedFormat.value}`
  return downloadMap[key] || downloadMap['base-memorystick']
})

const onDownloadClicked = () => {
  // Download started
}
</script>
