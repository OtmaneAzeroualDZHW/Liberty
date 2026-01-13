#!/bin/bash

# Update Paketliste
apt-get update

# Installiere Tesseract-OCR
apt-get install -y tesseract-ocr

# Installiere Poppler (für pdf2image)
apt-get install -y poppler-utils

# Installiere Python-Abhängigkeiten
pip install -r requirements.txt

