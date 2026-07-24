#!/bin/sh
python3 -m pip uninstall ocrmypdf_appleocr
rm -rf dist
python3 -m build
python3 -m pip install dist/*.tar.gz
