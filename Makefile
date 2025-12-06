.PHONY: format lint typecheck test bench clean install

install:
	pip install -e ".[dev]"

format:
	black raptor_pipeline tests
	ruff check --fix raptor_pipeline tests

lint:
	ruff check raptor_pipeline tests
	black --check raptor_pipeline tests

typecheck:
	mypy raptor_pipeline

test:
	pytest tests

bench:
	pytest tests -k bench --benchmark-only

clean:
	rm -rf build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .mypy_cache .pytest_cache .ruff_cache
	rm -rf raptor_data
