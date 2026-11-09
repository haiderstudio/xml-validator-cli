#!/bin/sh
# Run the XML checker on the whole examples/ folder.
cd "$(dirname "$0")/.." || exit 1
python3 src/xml_validator.py examples
