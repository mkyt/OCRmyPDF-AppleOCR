#!/bin/sh
rm -rf tmp
mkdir -p tmp
TMPDIR=./tmp python3 -m ocrmypdf --plugin ocrmypdf_appleocr -v --keep-temporary-files --optimize 2 $@

