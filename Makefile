.PHONY: format lint typecheck clean install graph

install:
	uv sync --all-extras

graph:
	@if [ -z "$(DATA)" ]; then \
		echo "Error: DATA parameter required. Usage: make graph DATA=./raptor_data"; \
		exit 1; \
	fi
	@DATA_EXPANDED=$$(eval echo "$(DATA)"); \
	uv run python -m src.Visualizer --data "$$DATA_EXPANDED" --output network_map.html

lint:
	uv run ruff check src/ profiles/
	uv run mypy --strict src/

clean:
	rm -rf build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .mypy_cache .pytest_cache .ruff_cache
	rm -rf raptor_data
	rm -rf .venv
