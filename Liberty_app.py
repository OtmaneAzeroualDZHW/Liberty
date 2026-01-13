from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.responses import StreamingResponse
from starlette.staticfiles import StaticFiles

from pdf2image import convert_from_bytes
import pytesseract
import os
from PIL import Image
from io import BytesIO
import re
import base64
import json
import zipfile
from typing import List

# ---------------------------------------------------------
# APP + STATIC
# ---------------------------------------------------------
app = FastAPI()
app.mount("/static", StaticFiles(directory="assets"), name="static")

# --- Pfade zu Tesseract und Poppler (anpassen falls nötig) ---
pytesseract.pytesseract.tesseract_cmd = r"C:\Users\Otman\Tesseract-OCR\tesseract.exe"
os.environ['TESSDATA_PREFIX'] = r"C:\Users\Otman\Tesseract-OCR\tessdata"
POPPLER_PATH = r"C:\Users\Otman\poppler-25.11.0\Library\bin"

# ---------------------------------------------------------
# FELDER
# ---------------------------------------------------------
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

# Globaler Speicher für letzte Ergebnisse
# Kann entweder ein dict (single) oder dict(filename->data) für multi sein
last_results = None

# ----------------------------------------------------------
# EXTRAKTION (deine Logik weitgehend übernommen + leicht robustere Checks)
# ----------------------------------------------------------
def extract_fields(text: str) -> dict:
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

    # Strasse, Nr. und PLZ, Ort, Land
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

    match = re.search(r"(CH-\d{4}\s+[A-Za-zäöüß\-]+)", text)
    results["PLZ, Ort, Land"] = match.group(1) if match else "Nicht gefunden"

    match = re.search(r"\b(CH|DE|AT|FR|IT)\b", text)
    results["Nationalität"] = match.group(0) if match else "Nicht gefunden"

    results["Telefon"] = "Nicht gefunden"
    for i, line in enumerate(lines):
        if re.search(r"Telefon", line, re.IGNORECASE):
            if i + 1 < len(lines):
                match = re.findall(r"\d{2,3}", lines[i + 1])
                if match:
                    results["Telefon"] = " ".join(match[:4])
                    break

    results["Geburtsdatum"] = "Nicht gefunden"
    for i, line in enumerate(lines):
        if re.search(r"Geburtsdatum", line, re.IGNORECASE):
            if i + 1 < len(lines):
                match = re.search(r"\d{2}\.\d{2}\.\d{4}", lines[i + 1])
                if match:
                    results["Geburtsdatum"] = match.group(0)
                    break

    match = re.search(r"(\d{3}\.\d{4}\.\d{4}\.\d{2})", text)
    results["Versichertennummer (AHV)"] = match.group(1) if match else "Nicht gefunden"

    match = re.search(r"\b(ledig|verheiratet|geschieden|verwitwet)\b", text, re.IGNORECASE)
    results["Zivilstand, Heiratsdatum"] = match.group(0) if match else "Nicht gefunden"

    results["E-Mail-Adresse"] = "Nicht gefunden"
    for i, line in enumerate(lines):
        if re.search(r"E-?Mail", line, re.IGNORECASE):
            if i + 1 < len(lines):
                match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", lines[i + 1])
                if match:
                    results["E-Mail-Adresse"] = match.group(0).strip()
                    break
            match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", line)
            if match:
                results["E-Mail-Adresse"] = match.group(0).strip()
                break

    # Sicherstellen, dass alle FIELDS vorhanden sind
    for f in FIELDS:
        if f not in results:
            results[f] = "Nicht gefunden"

    return results
# ----------------------------------------------------------
# HOMEPAGE mit Single + Multi Upload (korrekte name/multiple)
# ----------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def read_form():
    return f"""
    <html>
    <head>
        <title>Liberty Form Extract</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body {{
                background-color: #ffffff; /* komplett weiß */
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                padding: 20px;
            }}
            .logo {{
                height: 60px;
            }}
            .preview-img {{
                max-width: 100%;
                border-radius: 8px;
                border: 1px solid #dee2e6;
                margin-bottom: 10px;
            }}
            .card {{
                border-radius: 12px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.06);
                margin-top: 20px;
            }}
            h5 {{
                color: #0d6efd;
                margin-bottom: 15px;
            }}
            .btn {{
                font-weight: 600;
                padding: 10px;
                border-radius: 8px;
                font-size: 1rem;
            }}
            .btn-primary {{
                background-color: #0d6efd;
                border: none;
            }}
            .btn-primary:hover {{
                background-color: #0b5ed7;
            }}
            .btn-success {{
                background-color: #198754;
                border: none;
            }}
            .btn-success:hover {{
                background-color: #157347;
            }}
            .btn-outline-primary {{
                color: #0d6efd;
                border-color: #0d6efd;
            }}
            .btn-outline-primary:hover {{
                background-color: #0d6efd;
                color: white;
            }}
            .btn-outline-secondary {{
                color: #6c757d;
                border-color: #6c757d;
            }}
            .btn-outline-secondary:hover {{
                background-color: #6c757d;
                color: white;
            }}
            .table th {{
                background-color: #e9f2ff;
            }}
            .text-muted {{
                font-size: 0.9rem;
            }}
            .btn-container {{
                margin-top: 15px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="d-flex align-items-center mb-4">
                <img src="/static/liberty-logo.png" alt="Liberty Logo" class="logo me-3">
            </div>

            <div class="row">
                <!-- Uploadbereich -->
                <div class="col-md-4">
                    <div class="card p-4">
                        <h5>Formular(e) hochladen</h5>
                        <form id="uploadForm" action="/extract" enctype="multipart/form-data" method="post">
                            <input class="form-control mb-3" name="file" type="file" id="singleFile" accept=".pdf,.png,.jpg,.jpeg">
                            <button class="btn btn-primary w-100 mb-3" type="submit">Einzelnes Formular extrahieren</button>
                        </form>

                        <form id="uploadMultiForm" action="/extract-multi" enctype="multipart/form-data" method="post">
                            <input class="form-control mb-3" name="files" type="file" multiple id="multiFiles" accept=".pdf,.png,.jpg,.jpeg">
                            <button class="btn btn-success w-100" type="submit">Mehrere Formulare extrahieren</button>
                        </form>
                    </div>
                </div>

                <!-- Vorschau & erkannte Felder -->
                <div class="col-md-8">
                    <div id="results_container">
                        <div class="card p-3 mb-3">
                            <h5>Vorschau</h5>
                            <div id="preview_content">
                                <p class="text-muted">Nach dem Upload erscheinen hier die Vorschaubilder der Dokumente.</p>
                            </div>
                        </div>

                        <div class="card p-3">
                            <h5>Erkannte Informationen</h5>
                            <div id="fields_content">
                                <table class="table table-bordered">
                                    <thead class="table-light">
                                        <tr><th>Feld</th><th>Wert</th></tr>
                                    </thead>
                                    <tbody>
                                        {"".join([f"<tr><td>{f}</td><td>Nicht gefunden</td></tr>" for f in FIELDS])}
                                    </tbody>
                                </table>
                            </div>
                            <div class="btn-container d-flex gap-2">
                                <a href="/export/json?download=1" class="btn btn-outline-primary flex-fill">JSON herunterladen</a>
                                <a href="/" class="btn btn-outline-secondary flex-fill">← Zurück</a>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <script>
            const singleFileInput = document.getElementById('singleFile');
            const multiFilesInput = document.getElementById('multiFiles');
            const previewContent = document.getElementById('preview_content');

            function renderPreview(files) {{
                previewContent.innerHTML = '';
                Array.from(files).forEach(file => {{
                    const reader = new FileReader();
                    reader.onload = e => {{
                        if(file.type.startsWith('image/')) {{
                            const img = document.createElement('img');
                            img.src = e.target.result;
                            img.className = 'preview-img';
                            previewContent.appendChild(img);
                        }} else {{
                            const p = document.createElement('p');
                            p.textContent = 'PDF-Datei: ' + file.name;
                            p.className = 'text-muted';
                            previewContent.appendChild(p);
                        }}
                    }};
                    if(file.type.startsWith('image/')) {{
                        reader.readAsDataURL(file);
                    }} else {{
                        const p = document.createElement('p');
                        p.textContent = 'PDF-Datei: ' + file.name;
                        p.className = 'text-muted';
                        previewContent.appendChild(p);
                    }}
                }});
            }}

            singleFileInput.addEventListener('change', e => renderPreview(e.target.files));
            multiFilesInput.addEventListener('change', e => renderPreview(e.target.files));
        </script>
    </body>
    </html>
    """

# ----------------------------------------------------------
# SINGLE FILE EXTRACT (gibt HTML-Response mit Vorschau + Tabelle)
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

    # OCR - Text sammeln
    text = ""
    preview_html = ""
    for img in images:
        gray = img.convert("L")
        text_page = pytesseract.image_to_string(gray, lang="deu")
        text += text_page + "\n"

        # Vorschau
        preview_img = img.copy()
        preview_img.thumbnail((800, 1100))
        buf = BytesIO()
        preview_img.save(buf, format="PNG")
        preview_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        preview_html += f'<div class="mb-2"><h6>Seite</h6><img class="img-fluid preview-img" src="data:image/png;base64,{preview_b64}"></div>'

    # Extraktion
    results = extract_fields(text)
    last_results = {"type": "single", "filename": file.filename, "data": results}

    # Tabelleninhalt
    rows_html = "".join([f"<tr><td>{f}</td><td>{results.get(f, 'Nicht gefunden')}</td></tr>" for f in FIELDS])

    return HTMLResponse(f"""
    <html>
    <head>
        <title>OCR Ergebnisse - Liberty</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            .preview-container {{
                max-height: 600px;
                overflow-y: auto;
                border: 1px solid #ddd;
                padding: 10px;
                border-radius: 5px;
                background-color: #f9f9f9;
            }}
            body {{
                background-color: #ffffff; /* komplett weiß */
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                padding: 20px;
            }}
            .logo {{
                height: 60px;
            }}
            .preview-img {{
                max-width: 100%;
                border-radius: 8px;
                border: 1px solid #dee2e6;
                margin-bottom: 10px;
            }}
            .card {{
                border-radius: 12px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.06);
                margin-top: 20px;
            }}
            h5 {{
                color: #0d6efd;
                margin-bottom: 15px;
            }}
            .btn {{
                font-weight: 600;
                padding: 10px;
                border-radius: 8px;
                font-size: 1rem;
            }}
            .btn-primary {{
                background-color: #0d6efd;
                border: none;
            }}
            .btn-primary:hover {{
                background-color: #0b5ed7;
            }}
            .btn-success {{
                background-color: #198754;
                border: none;
            }}
            .btn-success:hover {{
                background-color: #157347;
            }}
            .btn-outline-primary {{
                color: #0d6efd;
                border-color: #0d6efd;
            }}
            .btn-outline-primary:hover {{
                background-color: #0d6efd;
                color: white;
            }}
            .btn-outline-secondary {{
                color: #6c757d;
                border-color: #6c757d;
            }}
            .btn-outline-secondary:hover {{
                background-color: #6c757d;
                color: white;
            }}
            .table th {{
                background-color: #e9f2ff;
            }}
            .text-muted {{
                font-size: 0.9rem;
            }}
            .btn-container {{
                margin-top: 15px;
            }}
        </style>
    </head>
    <body>
        <div class="container mt-4">
            <div style="text-align: left; padding: 10px;">
                <img src="/static/liberty-logo.png" alt="Liberty Logo" style="height:50px;">
            </div>

            <div class="row">
                <div class="col-md-6">
                    <div class="card p-3">
                        <h5>Vorschau</h5>
                        <div class="preview-container">
                            {preview_html}
                        </div>
                    </div>
                </div>

                <div class="col-md-6">
                    <div class="card p-3">
                        <h5>Erkannte Informationen</h5>
                        <table class="table table-bordered">
                            <thead class="table-light"><tr><th>Feld</th><th>Wert</th></tr></thead>
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
# MULTI FILE EXTRACT (verarbeitet Liste von Dateien)
# ----------------------------------------------------------
@app.post("/extract-multi", response_class=HTMLResponse)
async def extract_multi(files: List[UploadFile] = File(...)):
    global last_results

    multi_results = {}  # filename -> extracted data
    previews_html = ""
    rows_html = ""

    for file in files:
        content = await file.read()

        if file.filename.lower().endswith(".pdf"):
            pages = convert_from_bytes(content, dpi=150, poppler_path=POPPLER_PATH)
        else:
            pages = [Image.open(BytesIO(content))]

        # OCR Text für dieses Dokument sammeln
        text = ""
        preview_per_file = ""
        for i, img in enumerate(pages):
            gray = img.convert("L")
            text += pytesseract.image_to_string(gray, lang="deu") + "\n"

            # Vorschau-Bild
            preview_img = img.copy()
            preview_img.thumbnail((600, 900))
            buf = BytesIO()
            preview_img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            preview_per_file += f'<div class="mb-2"><h6>{file.filename} — Seite {i+1}</h6><img class="img-fluid preview-img" src="data:image/png;base64,{b64}"></div>'

        data = extract_fields(text)
        multi_results[file.filename] = data

        # Ergänze Vorschaubereich
        previews_html += f'<div class="mb-4 card p-2">{preview_per_file}</div>'

        # Tabellenbereich
        rows_html += f"<tr><th colspan='2' class='table-primary'>{file.filename}</th></tr>"
        for f in FIELDS:
            rows_html += f"<tr><td>{f}</td><td>{data.get(f, 'Nicht gefunden')}</td></tr>"

    last_results = {"type": "multi", "data": multi_results}

    return HTMLResponse(f"""
    <html>
    <head>
        <title>OCR Ergebnisse (mehrere Dateien) - Liberty</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            .preview-container {{
                max-height: 600px;
                overflow-y: auto;
                border: 1px solid #ddd;
                padding: 10px;
                border-radius: 5px;
                background-color: #f9f9f9;
            }}
            h5 {{
                color: #0d6efd;
                margin-bottom: 15px;
            }}
        </style>
    </head>
    <body>
        <div class="container mt-4">
            <div style="text-align: left; padding: 10px;">
                <img src="/static/liberty-logo.png" alt="Liberty Logo" style="height:50px;">
            </div>

            <div class="row">
                <div class="col-md-6">
                    <div class="card p-3">
                        <h5>Vorschauen aller Dokumente</h5>
                        <div class="preview-container">
                            {previews_html}
                        </div>
                    </div>
                </div>

                <div class="col-md-6">
                    <div class="card p-3">
                        <h5>Erkannte Informationen (alle Dateien)</h5>
                        <table class="table table-bordered">
                            <thead class="table-light"><tr><th>Feld</th><th>Wert</th></tr></thead>
                            <tbody>{rows_html}</tbody>
                        </table>

                        <a href="/export/json?download=1" class="btn btn-success mt-2">JSON (alle) herunterladen</a>
                        <a href="/export/zip" class="btn btn-secondary mt-2">ZIP (alle JSONs) herunterladen</a>
                        <a href="/" class="btn btn-light mt-2">← Zurück</a>
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """)


# ----------------------------------------------------------
# EXPORT JSON (letzte Ergebnisse)
# ----------------------------------------------------------
@app.get("/export/json")
def export_json(download: int = 0):
    global last_results
    if last_results is None:
        return JSONResponse({"error": "Keine Ergebnisse vorhanden"})

    # JSON Inhalt je nach Typ
    content_obj = last_results
    content = json.dumps(content_obj, ensure_ascii=False, indent=4)

    if download == 1:
        return Response(
            content,
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="ocr_results.json"'}
        )

    return JSONResponse(content_obj)


# ----------------------------------------------------------
# EXPORT ZIP (alle JSONs aus last_results bei multi)
# ----------------------------------------------------------
@app.get("/export/zip")
def export_zip():
    global last_results
    if last_results is None:
        return JSONResponse({"error": "Keine Ergebnisse vorhanden"})

    # nur relevant, wenn multi
    if last_results.get("type") != "multi":
        return JSONResponse({"error": "ZIP Export nur nach einer Multi-Extraktion verfügbar"})

    multi_data = last_results.get("data", {})

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for filename, data in multi_data.items():
            json_name = f"{filename}.json"
            z.writestr(json_name, json.dumps(data, ensure_ascii=False, indent=4))
    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="ocr_results.zip"'}
    )

# ----------------------------------------------------------
# Ende Datei
# ----------------------------------------------------------

# python -m uvicorn Liberty_app:app --reload