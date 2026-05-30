import json
import logging
import subprocess
import time
import platform

from config import PELIGROSOS, EXIT_COMMANDS, USE_CLOUD_AI
from engines import speak, escuchar, intelligent_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

IS_WINDOWS = platform.system() == "Windows"

# ✅ Límite de tamaño para respuestas del LLM
MAX_RESPONSE_SIZE = 10000  # caracteres


def _extraer_json(texto: str) -> dict | None:
    """Extrae JSON válido del texto, con límite de tamaño."""
    if len(texto) > MAX_RESPONSE_SIZE:
        logging.warning(f"Respuesta muy larga ({len(texto)} chars), truncando")
        texto = texto[:MAX_RESPONSE_SIZE]
    
    inicio = texto.find("{")
    fin    = texto.rfind("}")
    if inicio == -1 or fin == -1 or fin <= inicio:
        return None
    try:
        data = json.loads(texto[inicio:fin + 1])
        if "tipo" in data:
            return data
    except json.JSONDecodeError as e:
        logging.debug(f"Error al parsear JSON: {e}")
    return None


def procesar_input(text: str) -> dict:
    """Procesa entrada del usuario y genera respuesta estructurada."""
    # ✅ Valida tamaño de entrada
    if len(text) > MAX_RESPONSE_SIZE:
        return {"tipo": "chat", "respuesta": "Tu mensaje es muy largo, por favor resume."}
    
    sistema = "Windows" if IS_WINDOWS else "Linux/macOS"
    prompt = f"""Eres JARVIS, asistente de IA en {sistema}.
Analiza este mensaje del usuario y responde ÚNICAMENTE con un JSON válido, sin markdown.

Mensaje: "{text}"

Si es conversación normal, responde:
{{"tipo": "chat", "respuesta": "tu respuesta natural aquí"}}

Si es una solicitud de acción del sistema, responde:
{{"tipo": "comando", "comando": "comando para {sistema}", "confirmacion": "frase corta confirmando la acción", "pide_confirmacion": false}}

Usa "pide_confirmacion": true SOLO si el comando es potencialmente destructivo o irreversible.
Solo el JSON, nada más."""

    raw = intelligent_engine(prompt)
    if not raw:
        return {"tipo": "chat", "respuesta": "Mis sistemas están sobrecargados."}

    cleaned = raw.strip()
    
    # ✅ Limpieza de markdown con límite de profundidad
    for tag in ["```json", "```"]:
        if cleaned.startswith(tag):
            cleaned = cleaned[len(tag):]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    # ✅ Valida tamaño antes de procesar
    if len(cleaned) > MAX_RESPONSE_SIZE:
        logging.warning(f"Respuesta limpiada muy larga ({len(cleaned)} chars)")
        cleaned = cleaned[:MAX_RESPONSE_SIZE]

    try:
        data = json.loads(cleaned)
        if "tipo" in data:
            return data
    except json.JSONDecodeError as e:
        logging.debug(f"Error al parsear JSON limpio: {e}")

    data = _extraer_json(cleaned)
    if data:
        return data

    return {"tipo": "chat", "respuesta": cleaned}


def ejecutar_comando(cmd: str) -> None:
    """Ejecuta un comando del sistema con manejo seguro de errores."""
    try:
        subprocess.run(cmd, shell=True, check=True, timeout=30)  # ✅ Timeout agregado
        speak("Hecho.")
    except FileNotFoundError:
        speak("Comando no encontrado.")
        logging.warning(f"Comando no encontrado: {cmd}")
    except subprocess.CalledProcessError as e:
        speak("El comando falló.")
        logging.error(f"Error ejecutando: {e}")
    except subprocess.TimeoutExpired:
        speak("El comando tardó demasiado.")
        logging.error(f"Timeout ejecutando: {cmd}")
    except Exception as e:
        speak("Error inesperado al ejecutar.")
        logging.error(f"Error: {e}")


def main() -> None:
    msg = "Sistema JARVIS en línea." + (" Gemini activo." if USE_CLOUD_AI else " Usando IA local.")
    speak(msg)

    while True:
        user_input = escuchar()

        if not user_input or len(user_input) < 2:
            time.sleep(0.5)
            continue

        print(f"Tú: {user_input}")

        if any(cmd in user_input.lower() for cmd in EXIT_COMMANDS):
            speak("Entendido. Volviendo a modo de espera.")
            break

        resultado = procesar_input(user_input)
        tipo = resultado.get("tipo", "chat")

        if tipo == "chat":
            speak(resultado.get("respuesta", "No tengo respuesta."))

        elif tipo == "comando":
            cmd       = resultado.get("comando", "")
            confirmar = resultado.get("confirmacion", "Ejecutando acción")
            pide_conf = resultado.get("pide_confirmacion", False)

            if not cmd:
                speak("No pude generar el comando.")
                continue

            if any(p in cmd for p in PELIGROSOS):
                speak("Comando bloqueado por seguridad.")
                logging.warning(f"Bloqueado: {cmd}")
                continue

            if pide_conf:
                speak(f"{confirmar}. ¿Confirmas?")
                time.sleep(1.0)
                confirmacion_input = escuchar()
                no_words = ["no", "cancel", "para", "detente", "espera", "no quiero"]
                if confirmacion_input and not any(r in confirmacion_input.lower() for r in no_words):
                    ejecutar_comando(cmd)
                else:
                    speak("Cancelado.")
            else:
                speak(confirmar)
                ejecutar_comando(cmd)


if __name__ == "__main__":
    main()
