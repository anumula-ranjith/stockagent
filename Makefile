# Usage: make <target>

.PHONY: install dev-install test lint fmt clean

install:
	pip install -r requirements.txt

dev-install:
	pip install -r requirements-dev.txt
	pip install -e .

test:
	pytest -q

lint:
	ruff check src tests
	black --check src tests

fmt:
	ruff check --fix src tests
	black src tests

clean:
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info
