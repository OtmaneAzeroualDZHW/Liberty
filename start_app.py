from pyngrok import ngrok
import uvicorn
from Liberty_app import app
# from main import app  # Dein FastAPI-Code

# --- Setze den echten Ngrok-Authtoken ---
ngrok.set_auth_token("36Vz1pWr0ANF26hAm82mS74pmBe_76DY1MseH2Lu2n3eA7jQw")

# --- Starte einen öffentlichen Ngrok-Tunnel auf Port 8000 ---
public_url = ngrok.connect(8000)
print(f"🚀 Deine App ist öffentlich verfügbar unter: {public_url}")

# --- Starte FastAPI ---
uvicorn.run(app, host="0.0.0.0", port=8000)

# python start_app.py
