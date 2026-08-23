
# ----------- release -----------

include ../../config.mak

THEME ?= sugc
export THEME

../../tools/textfilter: ../../tools/textfilter.c
	make -C ../../tools/ textfilter

readme.txt: ../../tools/textfilter ../base_readme.txt ../../ChangeLog
	../../tools/textfilter ../base_readme.txt $@ PSP

rel: ../../EBOOT.PBP readme.txt ../game_def.cfg
	mkdir -p out/PicoDrive/skin/
	cp $^ out/PicoDrive/
	cp skin/* out/PicoDrive/skin/
	cp themes/$(THEME)/background.png out/PicoDrive/skin/
	cp themes/$(THEME)/background_selector.png out/PicoDrive/skin/
	cp themes/$(THEME)/background_title.png out/PicoDrive/skin/
	cd out && zip -9 -r ../../../PicoDrive_psp_$(VER).zip *
	rm -rf out
