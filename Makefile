# You can set these variables from the command line, and also from the environment for the first two.
SOURCEDIR     = source
BUILDDIR      = build
TESTDIR       = munggoggo/tests
MAKEFILE_LIST = /tmp/makefile_list.txt
MAKE          = make

.PHONY: all help clean build

# Put it first so that "make" without argument is like "make help".
help:
	@echo "$(MAKE) [all,clean,build]"

default: all

#all: unit
all: check clean build
	@echo "--------------------------------------------------------------------------------"
	@echo "-M- building
	@echo "--------------------------------------------------------------------------------"

test:
	./scripts/test

clean:
	@echo "Cleaning up..."
	#git clean -Xdf
	rm -rf dist

build:
	@echo "building and uploading"
	./scripts/publish
