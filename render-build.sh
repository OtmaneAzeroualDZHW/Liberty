#!/usr/bin/env bash
# Install Tesseract OCR + Poppler auf Render-Linux
apt-get update
apt-get install -y tesseract-ocr poppler-utils

# Installiere Python-Abhängigkeiten
pip install -r requirements.txt

