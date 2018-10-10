#!/bin/bash

PYTHON_FILES="../pdfshuffler/*.py"
UI_FILES="../data/*.ui"

xgettext $UI_FILES $PYTHON_FILES -o pdfshuffler.pot

