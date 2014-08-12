all:

build_darwin:
	python build.py bdist_mac
	mv build build_darwin
	cp *.png build_darwin/Video\ Coverflow-0.0.0.app/Contents/MacOS

clean:
	$(RM) -r build_darwin *.pyc

.PHONY: all clean
