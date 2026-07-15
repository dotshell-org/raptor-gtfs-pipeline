.PHONY: build run clean graph

build:
	./gradlew build

run:
	./gradlew run --args="$(ARGS)"

graph:
	@if [ -z "$(DATA)" ]; then \
		echo "Error: DATA parameter required. Usage: make graph DATA=./raptor_data"; \
		exit 1; \
	fi
	./gradlew run --args="visualize --data \"$(DATA)\" --output network_map.html"

clean:
	./gradlew clean
	rm -rf raptor_data
