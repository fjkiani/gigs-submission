.PHONY: install test lint typecheck demo check clean

PYTHON ?= python

install:
	uv pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check .

typecheck:
	mypy task1_audit

# Task 1 demo: runs grounding_check on three example tuples and prints verdicts
demo:
	$(PYTHON) -m task1_audit.demo

check: lint typecheck test

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
