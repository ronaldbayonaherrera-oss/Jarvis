import os
from dotenv import load_dotenv

load_dotenv()

# --- IA en la nube ---
API_KEY          = os.getenv("GOOGLE_API_KEY", "")
USE_CLOUD_AI     = bool(API_KEY)
CLOUD_MODEL_NAME = "gemini-2.0-flash"  # ✅ Modelo correcto y disponible

# --- llama.cpp local ---
LOCAL_AI_URL     = "http://127.0.0.1:8080/v1/chat/completions"
LOCAL_MODEL_NAME = "llama3.2:3b"

# --- Grabación (PC) ---
SAMPLE_RATE = 16000
CHANNELS    = 1

# --- Seguridad ---
PELIGROSOS = [
    "rm -rf", "mkfs", "fdisk", "parted",
    "dd if=", "chown -R", "chmod -R",
    "format c:", "del /f /s /q",
    "rd /s /q",
]

# --- Comandos para salir ---
EXIT_COMMANDS = [
    "adiós", "adios", "chao", "chau", "hasta luego", "nos vemos",
    "bye", "goodbye", "me voy", "eso es todo", "para", "detente",
    "descansa", "modo espera", "desconéctate", "shutdown"
]
