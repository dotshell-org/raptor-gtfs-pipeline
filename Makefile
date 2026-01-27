.PHONY: format lint typecheck test bench clean install run

install:
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"

run:
	@if [ -z "$(GTFS)" ]; then \
		echo "Error: GTFS parameter required. Usage: make run GTFS=path/to/gtfs"; \
		exit 1; \
	fi
	@GTFS_EXPANDED=$$(eval echo "$(GTFS)"); \
	if [ -f "$$GTFS_EXPANDED" ] && echo "$$GTFS_EXPANDED" | grep -q '\.zip$$'; then \
		echo "Extracting GTFS ZIP file: $$GTFS_EXPANDED"; \
		rm -rf ./temp_gtfs; \
		mkdir -p ./temp_gtfs; \
		unzip -q "$$GTFS_EXPANDED" -d ./temp_gtfs; \
		GTFS_DIR=$$(find ./temp_gtfs -name "*.txt" -exec dirname {} \; | head -1); \
		if [ -n "$$GTFS_DIR" ]; then \
			python -m raptor_pipeline.cli convert --input "$$GTFS_DIR" --output ./raptor_data --format binary; \
		else \
			python -m raptor_pipeline.cli convert --input ./temp_gtfs --output ./raptor_data --format binary; \
		fi; \
		rm -rf ./temp_gtfs; \
	else \
		python -m raptor_pipeline.cli convert --input "$$GTFS_EXPANDED" --output ./raptor_data --format binary; \
	fi

typecheck:
	mypy raptor_pipeline

clean:
	rm -rf build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .mypy_cache .pytest_cache .ruff_cache
	rm -rf raptor_data
