"""
prueb.py — Grabador y transcriptor de voz con Whisper para Termux.

Uso:
    python prueb.py              # graba 5 segundos
    python prueb.py -t 10        # graba 10 segundos
    python prueb.py -l en        # transcribe en inglés
    python prueb.py --loop       # modo continuo (Ctrl+C para salir)
    python prueb.py -o out.txt   # guarda la transcripción en archivo
"""

import argparse
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path.home() / "Jarvis" / "whisper.cpp"


@dataclass
class Config:
    whisper_cli: Path = BASE_DIR / "build/bin/whisper-cli"
    model_path:  Path = BASE_DIR / "models/ggml-base.bin"
    audio_raw:   Path = BASE_DIR / "audio_temp.m4a"
    audio_wav:   Path = BASE_DIR / "audio.wav"
    sample_rate: int  = 16000
    channels:    int  = 1


CFG = Config()


# ---------- utilidades ----------

def log(msg: str) -> None:
    print(msg, flush=True)


def check_dependencies() -> None:
    """Verifica que existan los binarios y modelos requeridos."""
    faltantes = []

    for cmd in ("termux-microphone-record", "ffmpeg"):
        if shutil.which(cmd) is None:
            faltantes.append(cmd)

    if not CFG.whisper_cli.exists():
        faltantes.append(str(CFG.whisper_cli))
    if not CFG.model_path.exists():
        faltantes.append(str(CFG.model_path))

    if faltantes:
        log("❌ Faltan dependencias o archivos:")
        for f in faltantes:
            log(f"   - {f}")
        sys.exit(1)


def limpiar() -> None:
    for f in (CFG.audio_raw, CFG.audio_wav):
        try:
            f.unlink(missing_ok=True)
        except OSError:
            pass


@contextmanager
def cleanup_on_exit():
    try:
        yield
    finally:
        limpiar()


# ---------- pipeline ----------

def grabar(segundos: int) -> bool:
    log(f"🎤 Grabando {segundos} segundos... HABLA YA")
    limpiar()

    proc = subprocess.Popen(
        ["termux-microphone-record", "-f", str(CFG.audio_raw)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        time.sleep(segundos)
    except KeyboardInterrupt:
        log("\n⏹️  Grabación cancelada")
        proc.terminate()
        return False

    subprocess.run(
        ["termux-microphone-record", "-q"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    for _ in range(20):
        if CFG.audio_raw.exists() and CFG.audio_raw.stat().st_size > 0:
            return True
        time.sleep(0.1)

    log("❌ No se generó el archivo de audio")
    return False


def convertir() -> bool:
    log("🔄 Convirtiendo audio...")
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(CFG.audio_raw),
            "-ar", str(CFG.sample_rate),
            "-ac", str(CFG.channels),
            str(CFG.audio_wav),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    if result.returncode != 0 or not CFG.audio_wav.exists():
        log("❌ Error al convertir el audio")
        if result.stderr:
            log(result.stderr.decode(errors="ignore").strip())
        return False
    return True


def transcribir(idioma: str = "es") -> str:
    """Transcribe CFG.audio_wav con whisper-cli (grabación local)."""
    log("🧠 Transcribiendo con Whisper...")
    inicio = time.time()

    result = subprocess.run(
        [
            str(CFG.whisper_cli),
            "-m", str(CFG.model_path),
            "-f", str(CFG.audio_wav),
            "-l", idioma,
            "--no-timestamps",
        ],
        capture_output=True,
        text=True,
    )

    duracion = round(time.time() - inicio, 2)
    log(f"⏱️  Whisper tardó: {duracion} s")

    return result.stdout.strip()


def transcribir_archivo(ruta: str, idioma: str = "es") -> str:
    """
    Transcribe un archivo de audio externo (enviado desde otro celu).

    SIEMPRE convierte con ffmpeg primero — aunque la extensión sea .wav,
    termux-microphone-record puede guardar en formato comprimido (AMR, AAC)
    que whisper-cli no lee directamente.
    """
    ruta_path = Path(ruta)
    wav_tmp = ruta_path.with_suffix(".conv.wav")

    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(ruta_path),
                "-ar", str(CFG.sample_rate),
                "-ac", str(CFG.channels),
                str(wav_tmp),
            ],
            capture_output=True,
            timeout=30,
        )

        if result.returncode != 0 or not wav_tmp.exists():
            ruta_final = ruta_path
        else:
            ruta_final = wav_tmp

        log("🧠 Transcribiendo con Whisper...")
        inicio = time.time()

        resultado = subprocess.run(
            [
                str(CFG.whisper_cli),
                "-m", str(CFG.model_path),
                "-f", str(ruta_final),
                "-l", idioma,
                "--no-timestamps",
            ],
            capture_output=True,
            text=True,
        )

        duracion = round(time.time() - inicio, 2)
        log(f"⏱️  Whisper tardó: {duracion} s")

        return resultado.stdout.strip()

    finally:
        if wav_tmp.exists():
            wav_tmp.unlink(missing_ok=True)


# ---------- entrada ----------

def procesar(segundos: int, idioma: str, salida: Path | None) -> str:
    if not grabar(segundos):
        return ""
    if not convertir():
        return ""

    texto = transcribir(idioma)
    log("\n🧠 Resultado:")
    log(texto if texto else "🤫 No se detectó voz")

    if salida and texto:
        with salida.open("a", encoding="utf-8") as f:
            f.write(texto + "\n")
        log(f"💾 Guardado en {salida}")

    return texto


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Grabador y transcriptor con Whisper")
    p.add_argument("-t", "--tiempo", type=int, default=5, help="segundos a grabar (def: 5)")
    p.add_argument("-l", "--idioma", default="es", help="idioma del audio (def: es)")
    p.add_argument("-o", "--salida", type=Path, help="archivo donde guardar la transcripción")
    p.add_argument("--loop", action="store_true", help="modo continuo (Ctrl+C para salir)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    check_dependencies()

    with cleanup_on_exit():
        if args.loop:
            log("🔁 Modo continuo activado (Ctrl+C para salir)\n")
            try:
                while True:
                    procesar(args.tiempo, args.idioma, args.salida)
                    log("\n" + "─" * 40)
            except KeyboardInterrupt:
                log("\n👋 Saliendo...")
        else:
            procesar(args.tiempo, args.idioma, args.salida)


if __name__ == "__main__":
    main()
