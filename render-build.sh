#!/usr/bin/env bash

# Update System
apt-get update

# Poppler installieren (für pdf2image)
apt-get install -y poppler-utils

# Tesseract OCR installieren
apt-get install -y tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng

# Python-Abhängigkeiten installieren
pip install -r requirements.txt
