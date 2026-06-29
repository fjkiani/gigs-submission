.PHONY: install test lint typecheck demo demo-task2 check clean

PYTHON ?= python

install:
	uv pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check .

typecheck:
	mypy --strict task1_audit task2_cashcard

# Task 1 demo: runs grounding_check on three example tuples and prints verdicts
demo:
	$(PYTHON) -m task1_audit.demo

# Task 2 demo: rich readiness + scorecard + KB-coverage tables
demo-task2:
	$(PYTHON) -m task2_cashcard.demo

check: lint typecheck test

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
