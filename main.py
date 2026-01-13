from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pdf2image import convert_from_bytes
import pytesseract
import os
from PIL import Image
from io import BytesIO
import re
import base64
import json

from starlette.staticfiles import StaticFiles

app = FastAPI()

# Assets (Bilder) bereitstellen
app.mount("/static", StaticFiles(directory="assets"), name="static")

# --- Pfade zu Tesseract und Poppler ---
pytesseract.pytesseract.tesseract_cmd = r"C:\Users\Otman\Tesseract-OCR\tesseract.exe"
os.environ['TESSDATA_PREFIX'] = r"C:\Users\Otman\Tesseract-OCR\tessdata"
POPPLER_PATH = r"C:\Users\Otman\poppler-25.11.0\Library\bin"

FIELDS = [
    "Anrede",
    "Name",
    "Vorname",
    "Strasse, Nr.",
    "PLZ, Ort, Land",
    "Nationalität",
    "Telefon",
    "Geburtsdatum",
    "Versichertennummer (AHV)",
    "Zivilstand, Heiratsdatum",
    "E-Mail-Adresse"
]

last_results = {}

# ----------------------------------------------------------
# EXTRAKTION
# ----------------------------------------------------------
# Hier kann man sagen welche Informationen müssen extrahiert werden
def extract_fields(text):
    results = {}

    # Anrede
    match = re.search(r"\b(Herr|Frau|Dr\.|Prof\.|Prof\. Dr\.)\b", text)
    results["Anrede"] = match.group(0) if match else "Nicht gefunden"

    # Name und Vorname
    results["Name"] = "Nicht gefunden"
    results["Vorname"] = "Nicht gefunden"

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    for i, line in enumerate(lines):
        if re.search(r"\bName\b", line, re.IGNORECASE):
            if i + 1 < len(lines):
                value = lines[i + 1].strip()
                words = value.split()
                if len(words) >= 2:
                    results["Vorname"] = words[0]
                    results["Name"] = " ".join(words[1:])
                else:
                    results["Name"] = value
        elif re.search(r"\bVorname\b", line, re.IGNORECASE):
            if results["Vorname"] == "Nicht gefunden" and i + 1 < len(lines):
                results["Vorname"] = lines[i + 1].strip()

    # Strasse, Nr.
    #match = re.search(r"([A-ZÄÖÜa-zäöüß\-]+\s\d+[a-zA-Z]?)", text)
    #results["Strasse, Nr."] = match.group(1) if match else "Nicht gefunden"

    results["Strasse, Nr."] = "Nicht gefunden"
    results["PLZ, Ort, Land"] = "Nicht gefunden"

    for i, line in enumerate(lines):
        if re.search(r"Strasse\s*,?\s*Nr\.?", line, re.IGNORECASE):
            # Prüfe, ob die Zeile ein ":" enthält
            if ":" in line:
                content = line.split(":")[1].strip()
            elif i + 1 < len(lines):
                content = lines[i + 1].strip()
            else:
                content = ""

            # Entferne führende einzelne Buchstaben + Leerzeichen (OCR-Artefakte)
            content = re.sub(r"^[A-Z]\s+", "", content)

            # Trenne Strasse+Nr. von PLZ+Ort falls vorhanden
            match = re.match(r"(.+?\d+[a-zA-Z]?)\s+(CH-\d{4}\s+.*)?", content)
            if match:
                results["Strasse, Nr."] = match.group(1).strip()
                if match.group(2):
                    results["PLZ, Ort, Land"] = match.group(2).strip()
            else:
                results["Strasse, Nr."] = content  # fallback

            break

    # PLZ, Ort, Land
    match = re.search(r"(CH-\d{4}\s+[A-Za-zäöüß\-]+)", text)
    results["PLZ, Ort, Land"] = match.group(1) if match else "Nicht gefunden"

    # Nationalität
    match = re.search(r"\b(CH|DE|AT|FR|IT)\b", text)
    results["Nationalität"] = match.group(0) if match else "Nicht gefunden"

    # Telefon
    #match = re.search(r"(\d{2,4}(?:[\s/-]\d{2,4})+)", text)
    #if match:
    # blocks = match.group(0).split()
    #   results["Telefon"] = " ".join(blocks[:4])
    #else:
    #    results["Telefon"] = "Nicht gefunden"
    results["Telefon"] = "Nicht gefunden"
    for i, line in enumerate(lines):
        if re.search(r"Telefon", line, re.IGNORECASE):
            if i + 1 < len(lines):
                # Suche nur nach 2- bis 3-stelligen Blöcken, max. 4 Blöcke
                match = re.findall(r"\d{2,3}", lines[i + 1])
                if match:
                    results["Telefon"] = " ".join(match[:4])  # nur die ersten 4 Blöcke
                    break
    # Geburtsdatum
    # match = re.search(r"(\d{2}\.\d{2}\.\d{4})", text)
    # results["Geburtsdatum"] = match.group(1) if match else "Nicht gefunden"

    results["Geburtsdatum"] = "Nicht gefunden"
    for i, line in enumerate(lines):
        if re.search(r"Geburtsdatum", line, re.IGNORECASE):
            if i + 1 < len(lines):
                match = re.search(r"\d{2}\.\d{2}\.\d{4}", lines[i + 1])
                if match:
                    results["Geburtsdatum"] = match.group(0)
                    break

    # AHV-Nr
    match = re.search(r"(\d{3}\.\d{4}\.\d{4}\.\d{2})", text)
    results["Versichertennummer (AHV)"] = match.group(1) if match else "Nicht gefunden"

    # Zivilstand
    match = re.search(r"\b(ledig|verheiratet|geschieden|verwitwet)\b", text, re.IGNORECASE)
    results["Zivilstand, Heiratsdatum"] = match.group(0) if match else "Nicht gefunden"

    # Email
    #match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", text)
    #results["E-Mail-Adresse"] = match.group(0) if match else "Nicht gefunden"

    results["E-Mail-Adresse"] = "Nicht gefunden"
    for i, line in enumerate(lines):
        if re.search(r"E-?Mail", line, re.IGNORECASE):
            # Nächste Zeile prüfen
            if i + 1 < len(lines):
                match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", lines[i + 1])
                if match:
                    results["E-Mail-Adresse"] = match.group(0).strip()
                    break
            # Falls direkt in der Zeile
            match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", line)
            if match:
                results["E-Mail-Adresse"] = match.group(0).strip()
                break

    # Alle FIELDS absichern
    for f in FIELDS:
        if f not in results:
            results[f] = "Nicht gefunden"

    return results

# ----------------------------------------------------------
# HOMEPAGE mit Logo
# ----------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def read_form():
    return f"""
    <html>
    <head>
        <title>Liberty Form Extract</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body {{ padding: 20px; }}
            .logo {{ height: 80px; }}
            .preview-img {{ max-width: 100%; border-radius: 5px; border: 1px solid #ddd; }}
            .card {{ margin-top: 20px; }}
            .table th, .table td {{ vertical-align: middle; }}
        </style>
    </head>
    <body>
        <div class="container">
           <div style="text-align: left; padding: 10px;">
            <img src="/static/liberty-logo.png" alt="Liberty Logo" style="height:50px;">
              <!--   <h2 class="mt-3">Liberty Form Extract</h2> -->
            </div>
            <div class="row mt-4">
                <div class="col-md-4">
                    <div class="card p-3">
                        <h5>Formular hochladen</h5>
                        <form action="/extract" enctype="multipart/form-data" method="post">
                            <input class="form-control" name="file" type="file" required><br>
                            <button class="btn btn-primary w-100" type="submit">Daten extrahieren</button>
                        </form>
                    </div>
                </div>
                <div class="col-md-8">
                    <div id="preview_area" class="card p-3">
                        <h5>Vorschau</h5>
                        <img id="preview_img" class="preview-img" src="" alt="Hier erscheint die Vorschau Ihres Dokuments nach dem Upload.">
                    </div>
                    <div id="results" class="card p-3 mt-3">
                        <h5>Erkannte Informationen</h5>
                        <table class="table table-bordered">
                            <thead class="table-light">
                                <tr><th>Feld</th><th>Wert</th></tr>
                            </thead>
                            <tbody>
                                {"".join([f"<tr><td>{f}</td><td>Nicht gefunden</td></tr>" for f in FIELDS])}
                            </tbody>
                        </table>

                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

# ----------------------------------------------------------
# EXTRACT ENDPOINT
# ----------------------------------------------------------
@app.post("/extract", response_class=HTMLResponse)
async def extract_form(file: UploadFile = File(...)):
    global last_results
    img_bytes = await file.read()

    # PDF oder Bild
    if file.filename.lower().endswith(".pdf"):
        images = convert_from_bytes(img_bytes, dpi=150, poppler_path=POPPLER_PATH)
    else:
        images = [Image.open(BytesIO(img_bytes))]

    # OCR
    text = ""
    for img in images:
        gray = img.convert("L")
        text += pytesseract.image_to_string(gray, lang="deu") + "\n"

    # Extraktion bleibt unverändert
    results = extract_fields(text)
    last_results = results

    # Tabelleninhalt
    rows_html = "".join([f"<tr><td>{f}</td><td>{results.get(f, 'Nicht gefunden')}</td></tr>" for f in FIELDS])

    # Vorschau für alle Seiten scrollbar
    preview_html = ""
    for img in images:
        preview_img = img.copy()
        preview_img.thumbnail((600, 800))
        buf = BytesIO()
        preview_img.save(buf, format="PNG")
        buf.seek(0)
        preview_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        preview_html += f'<div class="mb-2"><img class="img-fluid rounded shadow-sm" src="data:image/png;base64,{preview_base64}"></div>'

    return HTMLResponse(f"""
    <html>
    <head>
        <title>OCR Ergebnisse - Liberty</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            .preview-container {{
                max-height: 600px;        /* Höhe des scrollbaren Bereichs */
                overflow-y: auto;         /* Scrollbar */
                border: 1px solid #ddd;
                padding: 10px;
                border-radius: 5px;
                background-color: #f9f9f9;
            }}
        </style>
    </head>
    <body>
        <div class="container mt-4">
            <div style="text-align: left; padding: 10px;">
                <img src="/static/liberty-logo.png" alt="Liberty Logo" style="height:50px;">
            </div>

            <div class="row">
                <!-- Scrollbare Vorschau -->
                <div class="col-md-6">
                    <div class="card p-3">
                        <h5>Vorschau</h5>
                        <div class="preview-container">
                            {preview_html}
                        </div>
                    </div>
                </div>

                <!-- OCR-Ergebnisse -->
                <div class="col-md-6">
                    <div class="card p-3">
                        <h5>Erkannte Informationen</h5>
                        <table class="table table-bordered">
                            <thead class="table-light">
                                <tr><th>Feld</th><th>Wert</th></tr>
                            </thead>
                            <tbody>{rows_html}</tbody>
                        </table>

                        <a href="/export/json?download=1" class="btn btn-success mt-2">JSON herunterladen</a>
                        <a href="/" class="btn btn-secondary mt-2">← Zurück</a>
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """)


# ----------------------------------------------------------
# EXPORT JSON
# ----------------------------------------------------------
@app.get("/export/json")
def export_json(download: int = 0):
    content = json.dumps(last_results, ensure_ascii=False, indent=4)

    # JSON Download
    if download == 1:
        return Response(
            content,
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="ocr_results.json"'}
        )

    return JSONResponse(content=last_results)


# Ausführen-Zeile
#python -m uvicorn main:app --reload