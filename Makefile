.PHONY: format lint typecheck test bench clean install run run-lyon graph

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
			python -m raptor_pipeline.cli convert --input "$$GTFS_DIR" --output ./raptor_data --format binary --split-by-periods true; \
		else \
			python -m raptor_pipeline.cli convert --input ./temp_gtfs --output ./raptor_data --format binary --split-by-periods true; \
		fi; \
		rm -rf ./temp_gtfs; \
	else \
		python -m raptor_pipeline.cli convert --input "$$GTFS_EXPANDED" --output ./raptor_data --format binary --split-by-periods true; \
	fi

run-lyon:
	@if [ -z "$(GTFS)" ]; then \
		echo "Error: GTFS parameter required. Usage: make run-lyon GTFS=path/to/gtfs"; \
		exit 1; \
	fi
	@echo "🚇 Lyon TCL Mode: Generating 4 periods (school_on/school_off/saturday/sunday)"
	@GTFS_EXPANDED=$$(eval echo "$(GTFS)"); \
	if [ -f "$$GTFS_EXPANDED" ] && echo "$$GTFS_EXPANDED" | grep -q '\.zip$$'; then \
		echo "Extracting GTFS ZIP file: $$GTFS_EXPANDED"; \
		rm -rf ./temp_gtfs; \
		mkdir -p ./temp_gtfs; \
		unzip -q "$$GTFS_EXPANDED" -d ./temp_gtfs; \
		GTFS_DIR=$$(find ./temp_gtfs -name "*.txt" -exec dirname {} \; | head -1); \
		if [ -n "$$GTFS_DIR" ]; then \
			python -m raptor_pipeline.cli convert --input "$$GTFS_DIR" --output ./raptor_data --format binary --split-by-periods true --mode lyon; \
		else \
			python -m raptor_pipeline.cli convert --input ./temp_gtfs --output ./raptor_data --format binary --split-by-periods true --mode lyon; \
		fi; \
		rm -rf ./temp_gtfs; \
	else \
		python -m raptor_pipeline.cli convert --input "$$GTFS_EXPANDED" --output ./raptor_data --format binary --split-by-periods true --mode lyon; \
	fi

graph:
	@if [ -z "$(DATA)" ]; then \
		echo "Error: DATA parameter required. Usage: make graph DATA=./raptor_data"; \
		exit 1; \
	fi
	@DATA_EXPANDED=$$(eval echo "$(DATA)"); \
	python -m raptor_pipeline.visualize --data "$$DATA_EXPANDED" --output network_map.html

typecheck:
	mypy raptor_pipeline

clean:
	rm -rf build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .mypy_cache .pytest_cache .ruff_cache
	rm -rf raptor_data
