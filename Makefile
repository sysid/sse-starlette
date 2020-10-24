# You can set these variables from the command line, and also from the environment for the first two.
SOURCEDIR     = source
BUILDDIR      = build
MAKE          = make
VERSION       = $(shell cat sse_starlette/__init__.py | grep __version__ | sed "s/__version__ = //" | sed "s/'//g")

app_root = .
pkg_src =  $(app_root)/sse_starlette
tests_src = $(app_root)/tests

isort = isort --multi-line=3 --trailing-comma --force-grid-wrap=0 --combine-as --line-width 88 $(pkg_src) $(tests_src)
black = black $(pkg_src) $(tests_src)
mypy = mypy $(pkg_src)
#mypy = mypy --config-file $(app_root)/mypy.ini $(pkg_src)

.PHONY: all help clean build

# Put it first so that "make" without argument is like "make help".
.PHONY: help
help:
	@echo "$(MAKE) [all,clean,build]"

default: all

.PHONY: all
all: clean build upload tag
	@echo "--------------------------------------------------------------------------------"
	@echo "-M- building and distributing"
	@echo "--------------------------------------------------------------------------------"

test:
	./scripts/test

.PHONY: clean
clean:
	@echo "Cleaning up..."
	#git clean -Xdf
	rm -rf dist

.PHONY: build
build: black isort
	@echo "building"
	git add .
	git commit
	git push
	python setup.py sdist

.PHONY: upload
upload:
	@echo "upload"
	twine upload --verbose dist/*

.PHONY: tag
tag:
	@echo "tagging $(VERSION)"
	git tag -a $(VERSION) -m "version $(VERSION)"
	git push --tags

.PHONY: mypy
mypy:
	$(mypy)

.PHONY: black
black:
	$(black)

.PHONY: isort
isort:
	$(isort)
