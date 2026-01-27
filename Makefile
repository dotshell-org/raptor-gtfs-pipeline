.PHONY: format lint typecheck test bench clean install

install:
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"

typecheck:
	mypy raptor_pipeline

clean:
	rm -rf build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .mypy_cache .pytest_cache .ruff_cache
	rm -rf raptor_data
