.DEFAULT_GOAL := help

# You can set these variables from the command line, and also from the environment for the first two.
SOURCEDIR     = source
BUILDDIR      = build
MAKE          = make
VERSION       = $(shell cat sse_starlette/__init__.py | grep __version__ | sed "s/__version__ = //" | sed "s/'//g")

app_root = .
pkg_src =  $(app_root)/sse_starlette
tests_src = $(app_root)/tests

# pipx installed globals
isort = isort --multi-line=3 --trailing-comma --force-grid-wrap=0 --combine-as --line-width 88 $(pkg_src) $(tests_src)
black = black $(pkg_src) $(tests_src)
mypy = mypy $(pkg_src)
tox = tox
pipenv = pipenv
#mypy = mypy --config-file $(app_root)/mypy.ini $(pkg_src)

.PHONY: all help clean build

# Put it first so that "make" without argument is like "make help".
#.PHONY: help
#help:
#	@echo "$(MAKE) [all,clean,build]"

.PHONY: all
all: clean build upload tag  ## Build and upload
	@echo "--------------------------------------------------------------------------------"
	@echo "-M- building and distributing"
	@echo "--------------------------------------------------------------------------------"

test:  ## run tests
#	./scripts/test
	python -m pytest -ra

.PHONY: clean
clean:  ## clean
	@echo "Cleaning up..."
	#git clean -Xdf
	rm -rf dist

.PHONY: tox
tox:   ## Run tox
	$(tox)

.PHONY: coverage
coverage:  ## Run tests with coverage
	python -m coverage erase
	python -m coverage run --include=$(pkg_src)/* -m pytest -ra
	python -m coverage report -m

.PHONY: build
build: black isort  ## format and build
	@echo "building"
#	git add .
#	git commit
#	git push
	#python setup.py sdist
	python -m build

.PHONY: upload
upload:  ## upload to PyPi
	@echo "upload"
	twine upload --verbose dist/*

.PHONY: tag
tag:  ## tag
	@echo "tagging $(VERSION)"
	git tag -a $(VERSION) -m "version $(VERSION)"
	git push --tags

.PHONY: mypy
mypy:  ## type checking
	$(mypy)

.PHONY: black
black:  ## formatting with black
	$(black)

.PHONY: isort
isort:  ## sort imports
	$(isort)

.PHONY: bump
bump:  ## bump
	#bumpversion --dry-run --allow-dirty --verbose patch
	bumpversion --verbose patch

.PHONY: help
help: ## Show help message
	@IFS=$$'\n' ; \
	help_lines=(`fgrep -h "##" $(MAKEFILE_LIST) | fgrep -v fgrep | sed -e 's/\\$$//' | sed -e 's/##/:/'`); \
	printf "%s\n\n" "Usage: make [task]"; \
	printf "%-20s %s\n" "task" "help" ; \
	printf "%-20s %s\n" "------" "----" ; \
	for help_line in $${help_lines[@]}; do \
		IFS=$$':' ; \
		help_split=($$help_line) ; \
		help_command=`echo $${help_split[0]} | sed -e 's/^ *//' -e 's/ *$$//'` ; \
		help_info=`echo $${help_split[2]} | sed -e 's/^ *//' -e 's/ *$$//'` ; \
		printf '\033[36m'; \
		printf "%-20s %s" $$help_command ; \
		printf '\033[0m'; \
		printf "%s\n" $$help_info; \
	done
