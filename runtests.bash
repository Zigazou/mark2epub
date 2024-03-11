#!/usr/bin/env bash
export PYTHONPATH="$(pwd)/src":$PYTHONPATH
python3 tests/test_mark2epub.py