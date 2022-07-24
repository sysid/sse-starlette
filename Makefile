.DEFAULT_GOAL := help

# You can set these variables from the command line, and also from the environment for the first two.
SOURCEDIR     = source
BUILDDIR      = build
MAKE          = make
VERSION       = $(shell cat VERSION)

app_root = $(PROJ_DIR)
app_root ?= .
pkg_src =  $(app_root)/sse_starlette
tests_src = $(app_root)/tests

# pipx installed globals
#isort = isort --multi-line=3 --trailing-comma --force-grid-wrap=0 --combine-as --line-width 88 $(pkg_src) $(tests_src)
#black = black $(pkg_src) $(tests_src)
#mypy = mypy $(pkg_src)
#tox = tox
#pipenv = pipenv
#mypy = mypy --config-file $(app_root)/mypy.ini $(pkg_src)

define PRINT_HELP_PYSCRIPT
import re, sys

for line in sys.stdin:
	match = re.match(r'^([a-zA-Z0-9_-]+):.*?## (.*)$$', line)
	if match:
		target, help = match.groups()
		print("\033[36m%-20s\033[0m %s" % (target, help))
endef
export PRINT_HELP_PYSCRIPT

.PHONY: help
help:
	@python -c "$$PRINT_HELP_PYSCRIPT" < $(MAKEFILE_LIST)

.PHONY: clean
clean: clean-build clean-pyc  ## remove all build, test, coverage and Python artifacts

.PHONY: clean-build
clean-build: ## remove build artifacts
	rm -fr build/
	rm -fr dist/
	rm -fr .eggs/
	find . \( -path ./env -o -path ./venv -o -path ./.env -o -path ./.venv \) -prune -o -name '*.egg-info' -exec rm -fr {} +
	find . \( -path ./env -o -path ./venv -o -path ./.env -o -path ./.venv \) -prune -o -name '*.egg' -exec rm -f {} +

.PHONY: clean-pyc
clean-pyc: ## remove Python file artifacts
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -fr {} +

.PHONY: format
format:  ## perform black formatting
	black $(pkg_src) tests

.PHONY: isort
isort:  ## apply import sort ordering
	isort . --profile black

.PHONY: style
style: isort format  ## perform code style format (black, isort)

.PHONY: flake8
flake8:  ## check style with flake8
	@flake8 $(pkg_src)

.PHONY: mypy
mypy:  ## check type hint annotations
	# keep config in setup.cfg for integration with PyCharm
	mypy --config-file setup.cfg $(pkg_src)

.PHONY: tox
tox:   ## Run tox
	$(tox)

.PHONY: all
all: clean build upload tag  ## Build and upload
	@echo "--------------------------------------------------------------------------------"
	@echo "-M- building and distributing"
	@echo "--------------------------------------------------------------------------------"

.PHONY: coverage
coverage:  ## Run tests with coverage
	python -m coverage erase
	python -m coverage run --include=$(pkg_src)/* -m pytest -ra
	python -m coverage report -m

.PHONY: lint
lint: flake8 mypy ## lint code with all static code checks

test:  ## run tests
#	./scripts/test
	python -m pytest -ra

.PHONY: build
build: clean format isort  ## format and build
	@echo "building"
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

.PHONY: bump-major
bump-major:  ## bump-major
	bumpversion --commit --verbose major

.PHONY: bump-minor
bump-minor:  ## bump-minor
	bumpversion --verbose minor

.PHONY: bump-patch
bump-patch:  ## bump-patch
	#bumpversion --dry-run --allow-dirty --verbose patch
	bumpversion --verbose patch