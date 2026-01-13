#!/bin/bash
# Update Paketlisten
sudo apt-get update

# Installiere Poppler (für PDF-Konvertierung)
sudo apt-get install -y poppler-utils

# Installiere Tesseract OCR
sudo apt-get install -y tesseract-ocr

# Optional: Deutsche Sprache für Tesseract
sudo apt-get install -y tesseract-ocr-deu

