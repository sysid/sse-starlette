.DEFAULT_GOAL := help

# You can set these variables from the command line, and also from the environment for the first two.
SOURCEDIR     = source
BUILDDIR      = build
MAKE          = make
VERSION       = $(shell cat VERSION)
PACKAGE_NAME  = sse-starlette

app_root := $(if $(PROJ_DIR),$(PROJ_DIR),$(CURDIR))
pkg_src =  $(app_root)/sse_starlette
tests_src = $(app_root)/tests

.PHONY: all
all: clean build publish  ## Build and publish
	@echo "--------------------------------------------------------------------------------"
	@echo "-M- building and distributing"
	@echo "--------------------------------------------------------------------------------"

################################################################################
# Development \
DEVELOP: ## ############################################################

build-docker: ## build docker image
	@echo "building docker image"
	docker build --platform linux/amd64 --progress=plain -t sse_starlette .
	#docker tag $(IMAGE_NAME) 339712820866.dkr.ecr.eu-central-1.amazonaws.com/sse-starlette/sse-starlette:latest

################################################################################
# Building, Deploying \
BUILDING:  ## ############################################################
.PHONY: build
build: clean format  ## format and build
	@echo "building"
	python -m build

.PHONY: publish
publish:  ## publish
	@echo "upload to Pypi"
	twine upload --verbose dist/*

.PHONY: bump-major
bump-major:  check-github-token  ## bump-major, tag and push
	bump-my-version bump --commit --tag major
	git push
	git push --tags
	@$(MAKE) create-release

.PHONY: bump-minor
bump-minor:  check-github-token  ## bump-minor, tag and push
	bump-my-version bump --commit --tag minor
	git push
	git push --tags
	@$(MAKE) create-release

.PHONY: bump-patch
bump-patch:  check-github-token  ## bump-patch, tag and push
	bump-my-version bump --commit --tag patch
	git push
	git push --tags
	@$(MAKE) create-release

.PHONY: create-release
create-release: check-github-token  ## create a release on GitHub via the gh cli
	@if ! command -v gh &>/dev/null; then \
		echo "You do not have the GitHub CLI (gh) installed. Please create the release manually."; \
		exit 1; \
	else \
		echo "Creating GitHub release for v$(VERSION)"; \
		gh release create "v$(VERSION)" --generate-notes; \
	fi

.PHONY: check-github-token
check-github-token:  ## Check if GITHUB_TOKEN is set
	@if [ -z "$$GITHUB_TOKEN" ]; then \
		echo "GITHUB_TOKEN is not set. Please export your GitHub token before running this command."; \
		exit 1; \
	fi
	@echo "GITHUB_TOKEN is set"

################################################################################
# Testing \
TESTING:  ## ############################################################
.PHONY: test
test: test-unit test-docker  ## run tests
	#python -m pytest -ra --junitxml=report.xml --cov-config=pyproject.toml --cov-report=xml --cov-report term --cov=$(pkg_src) tests/
	#RUN_ENV=local python -m pytest -m "not (experimentation)" --cov-config=pyproject.toml --cov-report=html --cov-report=term --cov=$(pkg_src) tests
	:

.PHONY: test-unit
test-unit:  ## run all tests except "integration" marked
	RUN_ENV=local python -m pytest -m "not (integration or experimentation or loadtest)" --cov-config=pyproject.toml --cov-report=html --cov-report=term --cov=$(pkg_src) tests

.PHONY: test-docker
test-docker:  ## test-docker (docker desktop: advanced settings)
	@if [ -S /var/run/docker.sock > /dev/null 2>&1 ]; then \
		echo "Running docker tests because /var/run/docker.docker exists..."; \
		RUN_ENV=local python -m pytest -m "integration" tests; \
	else \
		echo "Skipping tests: /var/run/docker.sock does not exist."; \
	fi

.PHONY: test-load
test-load:  ## run load tests (requires docker, make test-load PYTEST_ARGS="--scale=500 --duration=5")
	@if [ -S /var/run/docker.sock > /dev/null 2>&1 ]; then \
		echo "Building load test image..."; \
		docker build -f tests/Dockerfile.loadtest -t sse-starlette-loadtest:latest .; \
		echo "Running load tests..."; \
		RUN_ENV=local python -m pytest -m "loadtest" tests/load/ -v --tb=short $(PYTEST_ARGS); \
	else \
		echo "Skipping load tests: /var/run/docker.sock does not exist."; \
	fi


################################################################################
# Code Quality \
QUALITY:  ## ############################################################

.PHONY: format
format:  ## perform ruff formatting
	@ruff format $(pkg_src) $(tests_src)

.PHONY: format-check
format-check:  ## perform black formatting
	@ruff format --check $(pkg_src) $(tests_src)

.PHONY: style
style: format  ## perform code style format

.PHONY: lint
lint:  ## check style with ruff
	ruff check $(pkg_src) $(tests_src)

.PHONY: mypy
mypy:  ## check type hint annotations
	@mypy --config-file pyproject.toml --install-types --non-interactive $(pkg_src)

.PHONY: pre-commit-install
pre-commit-install:  ## install pre-commit hooks
	pre-commit install

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
