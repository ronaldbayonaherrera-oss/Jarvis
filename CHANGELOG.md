# Changelog - Jarvis AI Assistant

## [v1.1.0] - 2026-05-30

### 🔧 Correcciones (Fixes)

#### config.py
- ✅ Actualizado modelo de Gemini: `gemini-3-flash-preview` → `gemini-2.0-flash` (modelo válido y disponible)

#### engines.py
- ✅ **Thread Safety**: Agregado `threading.Lock()` para proteger acceso a `_whisper_model` 
  - Problema: Race condition en entorno multihilo de Flask (`threaded=True`)
  - Solución: Sincronización con lock en `_get_whisper()`
- ✅ Mejora en manejo de excepciones de Gemini con logging mejorado

#### transcriptor.py
- ✅ **Atomic File Checks**: Creada función `_archivo_listo()` para verificación segura
  - Problema: Entre `.exists()` y `.stat()` el archivo podría desaparecer
  - Solución: Verificación atómica en un try/except
- ✅ Agregado logging estructurado

#### api.py
- ✅ **Filename Sanitization**: Agregada función `sanitizar_filename()` 
  - Problema: `archivo.filename` podría contener caracteres maliciosos o path traversal
  - Solución: Validación con regex, límite de longitud, solo caracteres seguros
- ✅ Mejorado manejo de limpieza de archivos temporales con try/except
- ✅ Agregado logging para errores

#### jarvis.py
- ✅ **Response Size Limits**: Constante `MAX_RESPONSE_SIZE = 10000` caracteres
  - Problema: Respuestas muy largas del LLM podrían causar problemas de memoria
  - Solución: Validación de tamaño antes y después de procesar
- ✅ **Timeout en Comandos**: Agregado `timeout=30` en `subprocess.run()`
  - Previene que comandos se cuelguen indefinidamente
- ✅ Mejorado manejo de excepciones en `ejecutar_comando()`

#### wake_word.py
- ✅ Agregado `timeout=3600` en ejecución de `jarvis.py`
- ✅ Mejorado manejo de errores en subprocess
- ✅ Agregado logging estructurado

### 📚 Documentación
- ✅ Agregado archivo CHANGELOG.md
- ✅ Comentarios mejorados en funciones críticas

### 🔐 Seguridad
- ✅ Sanitización de nombres de archivo (previene path traversal)
- ✅ Thread safety en acceso a objetos compartidos
- ✅ Límite de tamaño en respuestas del LLM
- ✅ Timeouts agregados en operaciones del sistema

---

## Notas Técnicas

### Race Conditions Arregladas
```python
# ANTES (inseguro)
if _whisper_model is None:
    _whisper_model = WhisperModel(...)

# DESPUÉS (seguro con lock)
with _whisper_lock:
    if _whisper_model is None:
        _whisper_model = WhisperModel(...)
```

### Validación de Archivos Mejorada
```python
# ANTES (vulnerable a TOCTOU)
if CFG.audio_raw.exists() and CFG.audio_raw.stat().st_size > 0:
    return True

# DESPUÉS (atómico)
return _archivo_listo(CFG.audio_raw)
```

### Sanitización de Entrada
```python
# Valida nombres de archivo contra path traversal
filename = sanitizar_filename(request.files["audio"].filename)
```
