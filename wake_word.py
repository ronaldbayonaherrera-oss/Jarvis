"""
wake_word.py — Detección continua de "Hey Jarvis" con openwakeword.

Captura audio del micrófono del sistema con sounddevice (Windows/macOS/Linux).
Al detectar la palabra clave, lanza jarvis.py automáticamente.

Requiere: ~/Jarvis/hey_jarvis.onnx
"""

import logging
import subprocess
import time
import threading
import queue
import sys
import platform
from pathlib import Path
from collections import deque

import numpy as np
import sounddevice as sd
import onnxruntime as ort
from openwakeword.utils import AudioFeatures

BASE_DIR       = Path.home() / "Jarvis"
WAKEWORD_MODEL = BASE_DIR / "hey_jarvis.onnx"
SAMPLE_RATE    = 16000
CLIP_SEGUNDOS  = 2

THRESHOLD      = 0.85
VENTANAS_CONF  = 1
COOLDOWN_SEG   = 3
VOLUMEN_MIN    = 0.003

DEBUG          = True

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

cola_audio = queue.Queue(maxsize=4)
detectado  = threading.Event()


class GrabadorContinuo(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.activo = True

    def _grabar_clip(self) -> np.ndarray | None:
        try:
            audio = sd.rec(
                int(CLIP_SEGUNDOS * SAMPLE_RATE),
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocking=True,
            )
            return audio.flatten()
        except Exception as e:
            logging.error(f"Error al grabar clip: {e}")
            return None

    def run(self):
        while True:
            if not self.activo or detectado.is_set():
                time.sleep(0.2)
                continue

            audio = self._grabar_clip()
            if audio is None:
                continue

            audio_f32 = audio.astype(np.float32) / 32768.0
            if np.abs(audio_f32).mean() < VOLUMEN_MIN:
                if DEBUG:
                    print("_", end="", flush=True)
                continue

            if not cola_audio.full():
                cola_audio.put_nowait(audio)
            else:
                try:
                    cola_audio.get_nowait()
                except queue.Empty:
                    pass
                cola_audio.put_nowait(audio)


class DetectorWakeWord(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.fe        = AudioFeatures()
        self.sess      = ort.InferenceSession(str(WAKEWORD_MODEL))
        self.buffer    = np.zeros(0, dtype=np.int16)
        self.historial = deque(maxlen=VENTANAS_CONF)

    def _analizar(self, audio: np.ndarray) -> float:
        self.buffer = np.concatenate([self.buffer, audio])

        ventana   = SAMPLE_RATE * 1
        paso      = ventana // 2
        max_score = 0.0

        while len(self.buffer) >= ventana:
            clip        = self.buffer[:ventana]
            self.buffer = self.buffer[paso:]

            batch = np.expand_dims(clip, axis=0)
            try:
                emb = self.fe.embed_clips(batch)
                if emb.ndim == 3:
                    emb = emb.mean(axis=1)
                resultado = self.sess.run(None, {"input": emb.astype(np.float32)})
                score = float(resultado[0][0])
                if score > max_score:
                    max_score = score
            except Exception as e:
                logging.error(f"Error en análisis: {e}")

        if len(self.buffer) > SAMPLE_RATE * 5:
            self.buffer = self.buffer[-SAMPLE_RATE * 2:]

        return max_score

    def run(self):
        ultimo_trigger = 0.0

        while True:
            try:
                audio = cola_audio.get(timeout=2)
            except queue.Empty:
                continue

            if time.time() - ultimo_trigger < COOLDOWN_SEG:
                continue

            score = self._analizar(audio)
            self.historial.append(score)

            if DEBUG and score > 0.3:
                barra = "█" * int(score * 20)
                print(f"\n  score: {score:.3f} {barra}", flush=True)

            if (len(self.historial) >= VENTANAS_CONF and
                    all(s > THRESHOLD for s in self.historial)):
                self.historial.clear()
                ultimo_trigger = time.time()
                detectado.set()


def main():
    if not WAKEWORD_MODEL.exists():
        raise FileNotFoundError(
            f"No se encontró el modelo: {WAKEWORD_MODEL}\n"
            "Copiá hey_jarvis.onnx en ~/Jarvis/"
        )

    logging.info(f"Sistema operativo: {platform.system()}")
    logging.info("Iniciando sistema de escucha continua con openwakeword...")
    logging.info(f"Umbral: {THRESHOLD} | Confirmación: {VENTANAS_CONF} ventanas | Cooldown: {COOLDOWN_SEG}s")

    grabador = GrabadorContinuo()
    detector = DetectorWakeWord()
    grabador.start()
    detector.start()

    print("\nSistema en espera... Di 'Hey Jarvis' para activar.")
    if DEBUG:
        print("Modo debug activo — verás la puntuación cuando hables.\n")
    print("Ctrl+C para salir.\n")

    python_cmd = sys.executable

    try:
        while True:
            if detectado.is_set():
                print("\n\n¡Hey Jarvis detectado! Activando asistente...\n")
                grabador.activo = False
                time.sleep(0.5)

                subprocess.run(
                    [python_cmd, str(Path(__file__).parent / "jarvis.py")],
                    cwd=str(BASE_DIR)
                )

                with cola_audio.mutex:
                    cola_audio.queue.clear()
                detector.historial.clear()
                detectado.clear()
                grabador.activo = True
                print("\nJarvis terminó. Volviendo a modo espera...\n")
            else:
                print(".", end="", flush=True)
                time.sleep(0.4)

    except KeyboardInterrupt:
        grabador.activo = False
        print("\nSistema apagado.")


if __name__ == "__main__":
    main()
