#!/bin/bash
# Example: Convert GTFS to binary format

set -e

# Convert minimal fixture
raptor-gtfs convert \
  --input tests/fixtures/gtfs_minimal \
  --output ./raptor_data \
  --format binary \
  --compression true

echo "Conversion complete! Output in ./raptor_data"
