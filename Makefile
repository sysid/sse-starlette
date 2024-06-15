.DEFAULT_GOAL := help

# You can set these variables from the command line, and also from the environment for the first two.
SOURCEDIR     = source
BUILDDIR      = build
MAKE          = make
VERSION       = $(shell cat VERSION)

app_root := $(if $(PROJ_DIR),$(PROJ_DIR),$(CURDIR))
pkg_src =  $(app_root)/sse_starlette
tests_src = $(app_root)/tests

.PHONY: all
all: clean build upload  ## Build and upload
	@echo "--------------------------------------------------------------------------------"
	@echo "-M- building and distributing"
	@echo "--------------------------------------------------------------------------------"

################################################################################
# Building, Deploying \
BUILDING:  ## ############################################################
.PHONY: build
build: clean format sort-imports  ## format and build
	@echo "building"
	#python -m build
	pdm build

.PHONY: publish
publish:  ## publish
	@echo "upload to Pypi"
	#twine upload --verbose dist/*
	#@git log -10 --pretty=format:"%h %aN %ar %d %s" | grep main | grep Bump && \
		#twine upload --verbose dist/* || \
		#echo "Bump Version before trying to upload"
	pdm publish

.PHONY: bump-major
bump-major:  ## bump-major, tag and push
	bump-my-version bump --commit --tag major
	git push
	git push --tags
	@$(MAKE) create-release

.PHONY: bump-minor
bump-minor:  ## bump-minor, tag and push
	bump-my-version bump --commit --tag minor
	git push
	git push --tags
	@$(MAKE) create-release

.PHONY: bump-patch
bump-patch:  ## bump-patch, tag and push
	bump-my-version bump --commit --tag patch
	git push
	git push --tags
	@$(MAKE) create-release

.PHONY: create-release
create-release:  ## create a release on GitHub via the gh cli
	@if command -v gh version &>/dev/null; then \
		echo "Creating GitHub release for v$(VERSION)"; \
		gh release create "v$(VERSION)" --generate-notes; \
	else \
		echo "You do not have the github-cli installed. Please create release from the repo manually."; \
		exit 1; \
	fi

################################################################################
# Testing \
TESTING:  ## ############################################################
.PHONY: test
test:  ## run tests
	python -m pytest -ra --junitxml=report.xml --cov-config=pyproject.toml --cov-report=xml --cov-report term --cov=$(pkg_src) tests/

.PHONY: test-unit
test-unit:  ## run all tests except "integration" marked
	RUN_ENV=local python -m pytest -m "not (integration or e2e)" --cov-config=pyproject.toml --cov-report=html --cov-report=term --cov=$(pkg_src) tests

.PHONY: tox
tox:   ## Run tox
	tox

################################################################################
# Code Quality \
QUALITY:  ## ############################################################

.PHONY: format
format:  ## perform ruff formatting
	@ruff format $(pkg_src) $(tests_src)

.PHONY: format-check
format-check:  ## perform black formatting
	@ruff format --check $(pkg_src) $(tests_src)

.PHONY: sort-imports
sort-imports:  ## apply import sort ordering
	isort $(pkg_src) $(tests_src) --profile black

.PHONY: style
style: sort-imports format  ## perform code style format (black, isort)

.PHONY: lint
lint:  ## check style with ruff
	ruff $(pkg_src) $(tests_src)

.PHONY: mypy
mypy:  ## check type hint annotations
	@mypy --config-file pyproject.toml --install-types --non-interactive $(pkg_src)

################################################################################
# Clean \
CLEAN:  ## ############################################################
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


################################################################################
# Misc \
MISC:  ## ############################################################
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
