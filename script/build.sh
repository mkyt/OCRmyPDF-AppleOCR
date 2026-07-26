#!/bin/sh
uv pip uninstall ocrmypdf_appleocr
rm -rf dist
uv pip install -e .
