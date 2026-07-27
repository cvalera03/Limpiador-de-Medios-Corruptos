# 🧹 Limpiador de Medios Corruptos (Imágenes y Videos)

![Python Version](https://img.shields.io/badge/Python-3.8%2B-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)

Una herramienta avanzada e intuitiva diseñada para escanear, detectar y limpiar **imágenes y videos corruptos o dañados** tras procesos de recuperación de datos (Photorec, Recuva, EaseUS, Stellar, etc.) o fallas en dispositivos de almacenamiento.

---

## 🌟 Características Principales

- **📊 Dashboard y Contador en Tiempo Real**: Muestra estadísticas en vivo (*Analizados*, *Válidos* y *Corruptos*) a medida que avanza el escaneo.
- **🛑 Botón de Detención Segura**: Permite pausar o cancelar el análisis en cualquier momento sin perder la lista de archivos corruptos encontrados hasta el momento.
- **⚡ Protección Anti-Bloqueo (Timeout de 2.5s)**: Incorpora un sistema de control de tiempo estricto por archivo para evitar congelamientos causados por archivos `.MOV` o `.MP4` con estructuras extremadamente dañadas.
- **🛡️ Modo Cuarentena (Recomendado)**: En lugar de borrar archivos directamente, los mueve a una subcarpeta `_Archivos_Corruptos` manteniendo la estructura de carpetas original.
- **🗑️ Eliminación Definitiva (Opcional)**: Opción para purgar permanentemente los archivos no recuperables.
- **📝 Informes Detallados**: Genera automáticamente un archivo `reporte_limpieza_corruptos.txt` con la causa exacta del error de cada archivo.
- **🎨 Interfaz Gráfica (GUI) y Consola (CLI)**: Funciona tanto con ventana intuitiva como mediante línea de comandos.

---

## 🔍 ¿Cómo Detecta la Corrupción?

La herramienta aplica una verificación en tres capas:

1. **Magic Bytes (Firmas de Cabecera)**: Comprueba los primeros bytes del archivo para confirmar que la firma coincida realmente con su extensión (ej. cabeceras `FF D8 FF` en JPG, `89 PNG` en PNG, `ftyp`/`moov` en MP4/MOV).
2. **Decodificación Estructural de Imagen (Pillow)**: Abre y carga la matriz de píxeles completa para detectar imágenes cortadas, truncadas o con corrupción de sectores.
3. **Decodificación de Video (OpenCV / FFmpeg)**: Inicializa el contenedor multimedia y lee los primeros fotogramas para asegurar que el códec de video pueda procesar la secuencia sin errores.

---

## 📂 Formatos Soportados

| Tipo | Extensiones |
| :--- | :--- |
| **Imágenes** | `.jpg`, `.jpeg`, `.png`, `.bmp`, `.webp`, `.gif`, `.tiff`, `.tif`, `.heic` |
| **Videos** | `.mp4`, `.mkv`, `.avi`, `.mov`, `.wmv`, `.flv`, `.webm`, `.m4v`, `.3gp` |

---

## 🚀 Instalación y Uso

### Requisitos Previos
Tener instalado **Python 3.8** o superior.

### 1. Clonar el Repositorio e Instalar Dependencias
```bash
git clone https://github.com/cvalera03/Limpiador-de-Medios-Corruptos.git
cd Limpiador-de-Medios-Corruptos
pip install -r requirements.txt
```

### 2. Ejecutar la Interfaz Gráfica (GUI)
Puedes iniciar la ventana gráfica ejecutando cualquiera de los dos archivos principales:

```bash
python LimpiadorCorruptos.py
```
o
```bash
python clean_corrupted_media.py
```

### 3. Usar mediante Línea de Comandos (CLI)
Para automatizar o escanear mediante comandos de consola:

* **Mover corruptos a cuarentena (por defecto):**
  ```bash
  python clean_corrupted_media.py --folder "C:\Ruta\A\Tu\Carpeta" --action quarantine
  ```

* **Eliminar corruptos permanentemente:**
  ```bash
  python clean_corrupted_media.py --folder "C:\Ruta\A\Tu\Carpeta" --action delete
  ```

* **Solo generar el reporte de diagnóstico:**
  ```bash
  python clean_corrupted_media.py --folder "C:\Ruta\A\Tu\Carpeta" --action report_only
  ```

---

## 📦 Crear un Ejecutable (.EXE) Portable para Windows

Si deseas usar esta aplicación en computadoras donde **no está instalado Python**:

1. Ejecuta el compilador automático:
   ```bash
   python build_exe.py
   ```
   *(O haz doble clic en `build_exe.bat`)*
2. Se generará una carpeta en `dist/LimpiadorMediosCorruptos/`.
3. Copia esa carpeta a cualquier memoria USB o PC para ejecutar directamente `LimpiadorMediosCorruptos.exe`.

---

## 📁 Estructura del Proyecto

```text
├── LimpiadorCorruptos.py      # Lanzador limpio sin consola gráfica
├── clean_corrupted_media.py   # Código fuente principal (Lógica + GUI Tkinter + CLI)
├── build_exe.py               # Script de compilación a ejecutable portable (.EXE)
├── Ejecutar_Limpiador.bat     # Lanzador directo para Windows
├── requirements.txt           # Dependencias Python (Pillow, OpenCV)
├── LICENSE                    # Licencia Open Source (MIT)
├── .gitignore                 # Archivo de exclusión para Git
└── README.md                  # Documentación del proyecto
```

---

## 📄 Licencia

Este proyecto es Open Source y está licenciado bajo la **[Licencia MIT](LICENSE)**. Eres libre de usarlo, modificarlo y distribuirlo libremente.
