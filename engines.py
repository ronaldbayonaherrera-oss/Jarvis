import logging
import time
import threading
import requests
import numpy as np
import pyttsx3
import sounddevice as sd
from scipy.io import wavfile
from pathlib import Path

from faster_whisper import WhisperModel
from google import genai

from config import (
    API_KEY, USE_CLOUD_AI, CLOUD_MODEL_NAME,
    LOCAL_AI_URL, LOCAL_MODEL_NAME,
    SAMPLE_RATE, CHANNELS,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BASE_DIR  = Path.home() / "Jarvis"
AUDIO_WAV = BASE_DIR / "audio_temp.wav"

# --- TTS con pyttsx3 ---
_tts_engine = pyttsx3.init()
_tts_engine.setProperty("rate", 175)

_voces = _tts_engine.getProperty("voices")
for v in _voces:
    if "spanish" in v.name.lower() or "es_" in v.id.lower() or "es-" in v.id.lower():
        _tts_engine.setProperty("voice", v.id)
        break

# --- Whisper (carga diferida con sincronización) ---
_whisper_model: WhisperModel | None = None
_whisper_lock = threading.Lock()  # ✅ Protege acceso a _whisper_model


def _get_whisper() -> WhisperModel:
    """Obtiene instancia de Whisper con thread-safety."""
    global _whisper_model
    with _whisper_lock:  # ✅ Sincronización
        if _whisper_model is None:
            logging.info("Cargando modelo Whisper base...")
            _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
        return _whisper_model


# --- Gemini ---
client_gemini = None
_gemini_desactivado = False

if USE_CLOUD_AI:
    try:
        client_gemini = genai.Client(api_key=API_KEY)
        logging.info(f"✅ Gemini listo: {CLOUD_MODEL_NAME}")
    except Exception as e:
        logging.error(f"⚠️ Gemini falló: {e}")
        _gemini_desactivado = True


# --- TTS ---
def speak(text: str) -> None:
    if not text:
        return
    print(f"JARVIS: {text}")
    try:
        _tts_engine.say(text)
        _tts_engine.runAndWait()
    except Exception as e:
        logging.error(f"Error TTS: {e}")


# --- Grabación ---
def _grabar(tiempo: int) -> bool:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        print(f"🎤 Escuchando... ({tiempo}s)")
        audio = sd.rec(
            int(tiempo * SAMPLE_RATE),
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
        )
        sd.wait()
        wavfile.write(str(AUDIO_WAV), SAMPLE_RATE, audio)
        return AUDIO_WAV.exists() and AUDIO_WAV.stat().st_size > 0
    except Exception as e:
        logging.error(f"Error al grabar: {e}")
        return False


# --- Escuchar y transcribir ---
def escuchar(tiempo: int = 5, idioma: str = "es") -> str:
    if not _grabar(tiempo):
        return ""
    try:
        model = _get_whisper()
        segments, _ = model.transcribe(
            str(AUDIO_WAV),
            language=idioma,
            beam_size=3,
        )
        return " ".join(seg.text for seg in segments).strip()
    except Exception as e:
        logging.error(f"Error al transcribir: {e}")
        return ""


# --- IA en la nube (Gemini) ---
def query_cloud_ai(prompt: str) -> str | None:
    global _gemini_desactivado
    if not USE_CLOUD_AI or not client_gemini or _gemini_desactivado:
        return None
    try:
        response = client_gemini.models.generate_content(
            model=CLOUD_MODEL_NAME, contents=prompt)
        return response.text.strip() if response and response.text else None
    except Exception as e:
        _gemini_desactivado = True
        logging.error(f"Gemini no disponible: {e}")
        print("Gemini no disponible. Cambiando a modelo local.")
        return None


# --- IA local (llama.cpp) ---
def query_local_ai(prompt: str) -> str | None:
    try:
        r = requests.post(
            LOCAL_AI_URL,
            json={
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Eres JARVIS. Responde ÚNICAMENTE con un objeto JSON válido. "
                            "Sin texto extra, sin explicaciones, sin markdown."
                        )
                    },
                    {"role": "user", "content": prompt}
                ],
                "stream": False,
                "temperature": 0.1,
                "max_tokens": 150
            },
            timeout=120
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip() or None
    except Exception as e:
        logging.error(f"❌ llama.cpp error: {e}")
        return None


# --- Motor principal ---
def intelligent_engine(prompt: str) -> str:
    if USE_CLOUD_AI:
        result = query_cloud_ai(prompt)
        if result:
            return result
    logging.info("Usando IA local como respaldo...")
    return query_local_ai(prompt) or ""
