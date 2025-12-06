#!/bin/bash
# Example: Validate binary output

set -e

# Validate output
raptor-gtfs validate --input ./raptor_data

echo "Validation complete!"
