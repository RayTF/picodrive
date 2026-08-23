# VectorDrive

A fork of PicoDrive for PSP, skinned to look like Sonic's Ultimate Genesis Collection

### Why?

In 2019 (when i originally had this idea) i had just gotten a PSP, and in 2016-2020 i had a copy of Sonic's UGC on the Xbox 360, i knew that the PSP was very much powerful enough to run the same library of games, and this was on the back of my head until August of 2024, when i finally gained enough skill to make this into a reality.

**Fun Fact** - I did make a **terrible** version of this idea in 2019 with my limited brain, which i still have archived today, (i stretched the SUGC logo to fit on the PBP, changed the background which made the game list almost unreadable, and a few other horrible hacks), but, it didn't involve any source code. This time i'm doing it for real, redesigning the UI and open sourcing all of it

### Downloads

Soon!

### To-do List

| Done     | Feature               | Progress |
|----------|-----------------------|----------|
| ✅ (M1)  | ISO Support           | 100%     |
| ✅ (M1)  | Game List             | 100%     |
| ✅ (M2)  | Title Screen          | 100%     |
| ✅ (M2)  | Backgrounds           | 100%     |
| ✅ (M2)  | SRAM in SAVEDATA      | 100%     |
| ✅ (M3)  | Retro Dreams BGM      | 100%     |
| ✅ (M3)  | Theme Switching       | 100%     |
| ✅ (M4)  | ROM Selector UI       | 100%     |
| ✅ (M5)  | ROM Metadata UI       | 100%     |
| ✳️ (V1)  | Customizer Tool       | 0%       |

### Q&A

**Q: Will you make this for the European version of Sonic's UGC (Sega Mega Drive Ultimate Collection // SEGA MDUC)?**
A: Originally i wasn't going to, but after making a separate branch to do it, i'm definitely going to release it. Up-to-date Development builds will ALWAYS be based on SUGC though.

**Q: Will you make a PS2 Port? It looks really similar to the PSP version!**
A: Never. I haven't owned a PS2 since 2013 (when i was a fucking baby) and don't plan to.

**Q: How can i add more games?**
A: Download or compile the Memory Stick version, go to or create the "rom" directory and add your games there, the file format doesn't matter

**Q: How do i compile on Windows?**
A: Not supported. I haven't used Windows as my daily OS since 2021 and have no plans to go back. Modern Windows is terrible and i have no reason to switch back. Just use a Linux VM if you can't make the switch

**Q: Does this work on PS Vita?**
A: Yes, just use Adrenaline and you're good, both the ISO and Memory Stick versions should work with no problem.

**Q: Does this work on PPSSPP?**
A: Absolutely! I used PPSSPP for testing the dev builds and it works flawlessly, but if you're gonna emulate SEGA Genesis games on an emulator, just use a normal Sega Genesis emulator, this is largely intended for people who own a PSP or PS Vita console.

**Q: How did you get an uncompressed version of the SUGC Intro and Soundtrack**
A: I ripped them myself from the Xbox 360 and PS3 version, just extract the files from the ISO and you should be good.

**Q: How did you figure out this really confusing source code?**
A: I admit that the PicoDrive source code is *almost* unreadable, and i definitely wouldn't recommend it to a beginner, but even if you are total trash at C code like i am, if you know where to look, it's not that hard, 99% of the changes were in the UI and the PSP-specific code, not on the emulator itself, i'm pretty sure it's possible to port this to Windows/Linux/PS2, but i have no desire in doing it myself, i can provide all of the design files, [my DMs are always open](https://raythefox.pw), message me and i'll be glad to help.
