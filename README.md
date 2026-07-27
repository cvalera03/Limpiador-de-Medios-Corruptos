# 🧹 Limpiador y Reparador de Medios Corruptos (Imágenes y Videos)

![Python Version](https://img.shields.io/badge/Python-3.8%2B-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)
![Recovery Rate](https://img.shields.io/badge/Recovery%20Rate-High%20(70%25%2B)-success.svg)

Una herramienta avanzada, profesional e intuitiva diseñada para escanear, detectar, separar e **intentar reparar exhaustivamente imágenes y videos corruptos o dañados** tras procesos de recuperación de datos (**Recuva, PhotoRec, EaseUS, Stellar, DiskDrill**, etc.) manteniendo la **estructura exacta de subcarpetas**.

---

## 🌟 Características Principales

- **🌳 Preservación del Árbol de Carpetas**: La carpeta `_Archivos_Reparados/` **mantiene exactamente la misma jerarquía de subcarpetas** del origen. Esto te permite copiar y pegar los archivos recuperados directamente sobre tu carpeta principal para dejarlos donde estaban.
- **🛠️ Motor de Reparación Exhaustiva Multi-Paso (6 Pasos para Fotos / 3 Pasos para Videos)**:
  - **Detección de formato real**: Identifica si un archivo tiene la extensión cambiada leyendo sus *Magic Bytes* binarios.
  - **Imágenes**: Recorte de basura previa a la firma SOI/PNG, reconstrucción de marcadores SOI/EOI (`FF D8`/`FF D9`), reparación de bloques IHDR/IEND en PNG, realineación RIFF en WEBP, renderizado de píxeles legibles sobre lienzo canvas (Pillow Truncated), rescate directo con OpenCV y conversión de emergencia entre formatos.
  - **Videos**: Re-extracción secuencial de fotogramas tolerante a fallos intermedios, rescate de flujos en bruto NAL H.264/H.265 (`00 00 00 01`) cuando falta el `moov atom`, y salvado de fotogramas estáticos como imagen de último recurso.
- **🛠️ Reparación Directa de Carpetas**: Botón **`🛠️ Reparar Carpeta Directa`** para procesar directamente carpetas de archivos corruptos previamente aisladas sin necesidad de re-analizarlas.
- **📊 Contador y Tasa de Éxito en Tiempo Real**: Visualización interactiva con porcentaje de recuperación (`📈 Tasa: XX%`), contadores de reparados/fallidos y barra de progreso fluida.
- **⚡ Proceso Asíncrono y Anti-Congelamiento**: Se ejecuta en hilos en segundo plano con **timeouts estrictos por archivo** (8s imágenes / 10s videos). Si un archivo está extremadamente destruido, el sistema lo salta automáticamente sin congelar la aplicación.
- **🔕 Consola Limpia**: Filtrado de mensajes de advertencia de bajo nivel de C++ (libpng, libjpeg, FFmpeg, OpenCV) para mantener la ventana de terminal completamente limpia.
- **🛡️ Manejo de Bloqueos de Archivo (`PermissionError / WinError 32`)**: Reintentos automáticos y copias de seguridad cuando Windows o antivirus bloquean temporalmente los archivos en uso.
- **📁 Separación Limpia de Carpetas**:
  - **`_Archivos_Reparados/`**: Copia limpia y funcional de todos los medios restaurados (preservando subcarpetas).
  - **`_Archivos_No_Reparables/`** / **`_Archivos_Corruptos/`**: Archivos originales dañados para su verificación.

---

## 📂 Formatos Soportados

| Tipo | Extensiones |
| :--- | :--- |
| **Imágenes** | `.jpg`, `.jpeg`, `.png`, `.bmp`, `.webp`, `.gif`, `.tiff`, `.tif`, `.heic` |
| **Videos** | `.mp4`, `.mkv`, `.avi`, `.mov`, `.wmv`, `.flv`, `.webm`, `.m4v`, `.3gp` |

---

## 🚀 Instalación y Uso

### 1. Clonar el Repositorio
```bash
git clone https://github.com/cvalera03/Limpiador-de-Medios-Corruptos.git
cd Limpiador-de-Medios-Corruptos
```

### 2. Instalar Dependencias
```bash
pip install -r requirements.txt
```

### 3. Ejecutar la Aplicación

#### Modo Interfaz Gráfica (Recomendado)
```bash
python LimpiadorCorruptos.py
```
O haciendo doble clic en **`Ejecutar_Limpiador.bat`**.

#### Modo Línea de Comandos (CLI)
```bash
# Reparación directa de una carpeta existente
python clean_corrupted_media.py -r "C:\Ruta\A\Carpeta_Corruptos"

# Escanear y reparar automáticamente
python clean_corrupted_media.py -f "C:\Ruta\A\Fotos_Y_Videos" -a repair
```

---

## 📄 Licencia

Este proyecto es Open Source y está licenciado bajo la **[Licencia MIT](LICENSE)**.
