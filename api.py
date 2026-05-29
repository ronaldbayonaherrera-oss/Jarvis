"""
Puente API para Whisper — accesible solo desde tu red WiFi local.

Uso:
    python api.py              # auto-detecta tu IP WiFi
    python api.py -p 8080      # cambia el puerto
    python api.py --publico    # sin restricción de IP (cuidado)

Endpoints:
    GET  /health               -> estado del servidor
    POST /transcribir          -> graba con el mic LOCAL y transcribe
        body JSON (todo opcional):
            { "tiempo": 5, "idioma": "es" }

    POST /transcribir-archivo  -> recibe audio del cliente y transcribe
        form-data:
            audio: <archivo WAV/OGG>
            idioma: "es"  (opcional)
        respuesta:
            { "ok": true, "texto": "...", "duracion_whisper_s": 1.83, "duracion_total_s": 2.01 }

Desde el otro celular (misma WiFi):
    curl -X POST http://<IP_DE_ESTE_CELU>:5000/transcribir-archivo \
         -F "audio=@grabacion.wav" \
         -F "idioma=es"
"""

import argparse
import ipaddress
import os
import socket
import tempfile
import threading
import time
from functools import wraps

from flask import Flask, jsonify, request

from transcriptor import (
    check_dependencies,
    convertir,
    grabar,
    limpiar,
    transcribir,
    transcribir_archivo,
)

app = Flask(__name__)
_lock = threading.Lock()

REDES_PERMITIDAS: list[ipaddress.IPv4Network] = []


# ── Helpers de red ────────────────────────────────────────────────────────────

def obtener_ip_wifi() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def ip_a_subred(ip: str) -> ipaddress.IPv4Network:
    return ipaddress.IPv4Network(f"{ip}/24", strict=False)


def ip_permitida(ip_cliente: str) -> bool:
    if not REDES_PERMITIDAS:
        return True
    try:
        addr = ipaddress.IPv4Address(ip_cliente)
        return any(addr in red for red in REDES_PERMITIDAS)
    except ValueError:
        return False


# ── Decorador de protección ──────────────────────────────────────────────────

def solo_red_local(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        ip = ip.split(",")[0].strip()
        if not ip_permitida(ip):
            app.logger.warning(f"Acceso denegado desde {ip}")
            return jsonify({"ok": False, "error": f"IP no autorizada: {ip}"}), 403
        return f(*args, **kwargs)
    return wrapper


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
@solo_red_local
def health():
    ip_wifi = obtener_ip_wifi()
    redes = [str(r) for r in REDES_PERMITIDAS] or ["sin restricción"]
    return jsonify({
        "ok": True,
        "servicio": "whisper-bridge",
        "ip_local": "127.0.0.1",
        "ip_wifi": ip_wifi,
        "redes_permitidas": redes,
    })


@app.route("/transcribir", methods=["POST"])
@solo_red_local
def transcribir_endpoint():
    """Graba con el micrófono LOCAL de este celu y transcribe."""
    data = request.get_json(silent=True) or {}

    try:
        tiempo = int(data.get("tiempo", 5))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "tiempo debe ser entero"}), 400

    idioma = str(data.get("idioma", "es"))

    if tiempo <= 0 or tiempo > 300:
        return jsonify({"ok": False, "error": "tiempo fuera de rango (1-300)"}), 400

    if not _lock.acquire(blocking=False):
        return jsonify({"ok": False, "error": "ya hay una transcripción en curso"}), 429

    inicio = time.time()
    try:
        if not grabar(tiempo):
            return jsonify({"ok": False, "error": "fallo al grabar"}), 500
        if not convertir():
            return jsonify({"ok": False, "error": "fallo al convertir audio"}), 500

        inicio_whisper = time.time()
        texto = transcribir(idioma)
        duracion_whisper = round(time.time() - inicio_whisper, 2)
        elapsed = round(time.time() - inicio, 2)

        return jsonify({
            "ok": True,
            "texto": texto,
            "idioma": idioma,
            "tiempo": tiempo,
            "duracion_whisper_s": duracion_whisper,
            "duracion_total_s": elapsed,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        limpiar()
        _lock.release()


@app.route("/transcribir-archivo", methods=["POST"])
@solo_red_local
def transcribir_archivo_endpoint():
    """Recibe un archivo de audio grabado en el cliente y lo transcribe."""
    if "audio" not in request.files:
        return jsonify({"ok": False, "error": "falta el campo 'audio' en el form-data"}), 400

    archivo = request.files["audio"]
    idioma = request.form.get("idioma", "es")

    if not _lock.acquire(blocking=False):
        return jsonify({"ok": False, "error": "ya hay una transcripción en curso"}), 429

    tmp_path = None
    inicio = time.time()
    try:
        sufijo = os.path.splitext(archivo.filename or "audio.wav")[1] or ".wav"
        with tempfile.NamedTemporaryFile(suffix=sufijo, delete=False) as tmp:
            archivo.save(tmp)
            tmp_path = tmp.name

        inicio_whisper = time.time()
        texto = transcribir_archivo(tmp_path, idioma)
        duracion_whisper = round(time.time() - inicio_whisper, 2)
        elapsed = round(time.time() - inicio, 2)

        return jsonify({
            "ok": True,
            "texto": texto,
            "idioma": idioma,
            "duracion_whisper_s": duracion_whisper,
            "duracion_total_s": elapsed,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
        _lock.release()


# ── Arranque ─────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Puente API para Whisper (solo WiFi local)")
    p.add_argument("-p", "--port", type=int, default=5000, help="puerto (def: 5000)")
    p.add_argument("--publico", action="store_true",
                   help="desactiva la restricción de IP (acepta cualquier origen)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    check_dependencies()

    ip_local = obtener_ip_wifi()

    if args.publico:
        print("ADVERTENCIA: modo público — cualquier IP puede conectarse")
    else:
        red = ip_a_subred(ip_local)
        REDES_PERMITIDAS.append(red)
        REDES_PERMITIDAS.append(ipaddress.IPv4Network("127.0.0.0/8"))

    print("=" * 55)
    print("  Servidor Whisper arrancando")
    print(f"  Tu IP WiFi  : {ip_local}")
    print(f"  Puerto      : {args.port}")
    if REDES_PERMITIDAS:
        print(f"  Red permitida: {REDES_PERMITIDAS[0]}")
        print()
        print(f"  Desde este mismo celu (local):")
        print(f"  http://127.0.0.1:{args.port}/transcribir-archivo")
        print()
        print(f"  Desde el otro celu (misma WiFi):")
        print(f"  http://{ip_local}:{args.port}/transcribir-archivo")
    print("=" * 55)
    print()

    app.run(host="0.0.0.0", port=args.port, threaded=True)


if __name__ == "__main__":
    main()