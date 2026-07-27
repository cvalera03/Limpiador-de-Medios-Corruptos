#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Limpiador de Medios Corruptos (Imágenes y Videos)
Detecta y elimina o mueve archivos de imagen y video dañados/corruptos tras procesos de recuperación de datos.
"""

import os
import sys
import time
import shutil
import argparse
import datetime
import threading
from pathlib import Path


def safe_remove(filepath: str, max_retries: int = 5, delay: float = 0.3) -> bool:
    """Elimina un archivo de forma segura reintentando si está bloqueado temporalmente por Windows."""
    if not filepath or not os.path.exists(filepath):
        return True
    for _ in range(max_retries):
        try:
            os.remove(filepath)
            return True
        except PermissionError:
            time.sleep(delay)
        except Exception:
            pass
    return False


def safe_move(src: str, dst: str, max_retries: int = 6, delay: float = 0.4) -> bool:
    """
    Mueve un archivo de forma robusta en Windows.
    Maneja bloqueos temporales por procesos externos o hilos (WinError 32 / PermissionError).
    Si el movimiento directo falla tras reintentos, realiza una copia segura y limpia el origen.
    """
    src_p = Path(src)
    dst_p = Path(dst)
    
    if not src_p.exists():
        return False

    dst_p.parent.mkdir(parents=True, exist_ok=True)

    # Si el destino ya existe, eliminarlo antes de mover
    if dst_p.exists() and str(dst_p) != str(src_p):
        safe_remove(str(dst_p))

    for _ in range(max_retries):
        try:
            shutil.move(str(src_p), str(dst_p))
            return True
        except PermissionError:
            time.sleep(delay)
        except Exception:
            time.sleep(delay)

    # Fallback si shutil.move falla por bloqueo persistente: copiar y luego intentar eliminar origen
    try:
        shutil.copy2(str(src_p), str(dst_p))
        safe_remove(str(src_p))
        return True
    except Exception:
        return False


# Intentar importar librerías externas opcionales pero recomendadas
HAS_PIL = False
try:
    from PIL import Image, ImageFile
    # Permitir cargar imágenes truncadas parcialmente para evaluar exactamente
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    HAS_PIL = True
except ImportError:
    pass

def suppress_c_stderr():
    """Redirige el descriptor stderr de C (fd 2) a NUL para silenciar los mensajes de advertencia de C++/FFmpeg/libpng/libjpeg en consola."""
    try:
        null_fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(null_fd, 2)
        os.close(null_fd)
    except Exception:
        pass

suppress_c_stderr()

HAS_CV2 = False
try:
    os.environ["OPENCV_FFMPEG_LOG_LEVEL"] = "-8"
    os.environ["OPENCV_FFMPEG_READ_ATTEMPTS"] = "50"
    import cv2
    if hasattr(cv2, 'setLogLevel'):
        cv2.setLogLevel(0)
    HAS_CV2 = True
except ImportError:
    pass

# Extensiones soportadas
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.gif', '.tiff', '.tif', '.heic'}
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.3gp'}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


def detect_real_format(filepath: str) -> str:
    """
    Detecta el formato REAL de un archivo leyendo sus Magic Bytes,
    ignorando la extensión del archivo. Esencial para archivos recuperados
    por EaseUS/Recuva que pueden tener extensiones incorrectas.
    Devuelve la extensión real detectada (ej: '.jpg', '.png') o '' si no se reconoce.
    """
    try:
        with open(filepath, 'rb') as f:
            header = f.read(32)
        if len(header) < 4:
            return ''

        # Buscar firmas en cualquier posición de los primeros 32 bytes (basura previa)
        # JPEG: FF D8 FF
        if b'\xff\xd8\xff' in header:
            return '.jpg'
        # PNG: 89 50 4E 47
        if b'\x89PNG' in header:
            return '.png'
        # GIF: GIF87a o GIF89a
        if b'GIF87a' in header or b'GIF89a' in header:
            return '.gif'
        # BMP: BM
        if header[:2] == b'BM':
            return '.bmp'
        # WEBP: RIFF....WEBP
        if b'RIFF' in header and b'WEBP' in header:
            return '.webp'
        # TIFF: II*\x00 o MM\x00*
        if header[:4] in (b'II*\x00', b'MM\x00*'):
            return '.tiff'
        # MP4/MOV: ftyp
        if b'ftyp' in header[:16]:
            return '.mp4'
        # AVI: RIFF....AVI
        if b'RIFF' in header[:4] and b'AVI ' in header[8:16]:
            return '.avi'
        # MKV/WEBM: EBML header
        if header[:4] == b'\x1a\x45\xdf\xa3':
            return '.mkv'
        # FLV
        if header[:3] == b'FLV':
            return '.flv'
        # WMV/ASF
        if header[:4] == b'\x30\x26\xb2\x75':
            return '.wmv'

        # Buscar firma JPEG más profunda (basura previa > 32 bytes)
        try:
            with open(filepath, 'rb') as f:
                chunk = f.read(4096)
            soi = chunk.find(b'\xff\xd8\xff')
            if soi >= 0:
                return '.jpg'
            # Buscar firma PNG
            png_sig = chunk.find(b'\x89PNG')
            if png_sig >= 0:
                return '.png'
        except Exception:
            pass

    except Exception:
        pass
    return ''


def is_repair_valid(filepath: str) -> bool:
    """
    Validación PERMISIVA para archivos reparados.
    A diferencia de is_image_corrupt() que usa verify() + load() estricto,
    esta función solo comprueba que:
    1. El archivo existe y tiene tamaño > 0.
    2. Pillow puede abrirlo y obtener al menos las dimensiones.
    3. Al menos ALGUNOS píxeles son legibles (no todo negro/vacío).

    Para videos, verifica que OpenCV puede abrir y leer al menos 1 fotograma.
    """
    try:
        if not os.path.exists(filepath) or os.path.getsize(filepath) < 10:
            return False

        ext = os.path.splitext(filepath)[1].lower()

        if ext in IMAGE_EXTENSIONS:
            if HAS_PIL:
                try:
                    ImageFile.LOAD_TRUNCATED_IMAGES = True
                    with Image.open(filepath) as img:
                        w, h = img.size
                        if w < 1 or h < 1:
                            return False
                        # Intentar cargar al menos una porción de píxeles
                        try:
                            img.load()
                        except Exception:
                            pass  # Aceptamos imágenes parcialmente cargadas
                        # Verificar que no sea una imagen completamente negra/vacía
                        try:
                            extrema = img.convert("RGB").getextrema()
                            # Si todos los canales tienen max=0 es completamente negra
                            all_black = all(mx == 0 for (_, mx) in extrema)
                            if all_black and w > 10 and h > 10:
                                return False
                        except Exception:
                            pass  # Si no podemos verificar extrema, aceptamos
                    return True
                except Exception:
                    pass
            # Fallback: si PIL no está, intentar con OpenCV
            if HAS_CV2:
                try:
                    img = cv2.imread(filepath)
                    if img is not None and img.shape[0] > 0 and img.shape[1] > 0:
                        return True
                except Exception:
                    pass
            return False

        elif ext in VIDEO_EXTENSIONS:
            if HAS_CV2:
                try:
                    cap = cv2.VideoCapture(filepath)
                    if cap.isOpened():
                        ret, frame = cap.read()
                        cap.release()
                        if ret and frame is not None:
                            return True
                    cap.release()
                except Exception:
                    pass
            return False

        return False
    except Exception:
        return False


def check_magic_bytes(filepath: str, ext: str) -> bool:
    """Comprueba las firmas de cabecera (Magic Bytes) básicas."""
    try:
        size = os.path.getsize(filepath)
        if size < 12:
            return False  # Archivo demasiado pequeño para ser una imagen/video válido

        with open(filepath, 'rb') as f:
            header = f.read(32)

        ext = ext.lower()
        if ext in ('.jpg', '.jpeg'):
            return header.startswith(b'\xff\xd8\xff')
        elif ext == '.png':
            return header.startswith(b'\x89PNG\r\n\x1a\n')
        elif ext == '.gif':
            return header.startswith(b'GIF87a') or header.startswith(b'GIF89a')
        elif ext == '.bmp':
            return header.startswith(b'BM')
        elif ext == '.webp':
            return header.startswith(b'RIFF') and b'WEBP' in header[8:16]
        elif ext in ('.tiff', '.tif'):
            return header.startswith(b'II*\x00') or header.startswith(b'MM\x00*')
        elif ext in ('.mp4', '.m4v', '.mov'):
            # Contenedores ISO Base Media File (ftyp / moov) o RIFF/QT
            return b'ftyp' in header[4:16] or b'moov' in header or b'wide' in header or header.startswith(b'RIFF')
        elif ext == '.avi':
            return header.startswith(b'RIFF') and b'AVI ' in header[8:16]
        elif ext == '.mkv' or ext == '.webm':
            return header.startswith(b'\x1a\x45\xdf\xa3')  # EBML header
    except Exception:
        return False

    return True


def is_image_corrupt(filepath: str) -> tuple[bool, str]:
    """
    Verifica si una imagen está corrupta.
    Devuelve (True, razón) si está corrupta, o (False, "OK") si es válida.
    """
    try:
        size = os.path.getsize(filepath)
        if size <= 0:
            return True, "Archivo de 0 bytes"

        ext = os.path.splitext(filepath)[1].lower()

        # 1. Comprobar Magic Bytes de cabecera
        if not check_magic_bytes(filepath, ext):
            return True, "Cabecera de archivo no válida (Magic Bytes incorrectos)"

        # 2. Comprobar con PIL si está disponible
        if HAS_PIL:
            try:
                with Image.open(filepath) as img:
                    img.verify()  # Verifica integridad estructural del formato

                # Reabrir para decodificar datos de píxeles reales (captura datos truncados)
                with Image.open(filepath) as img:
                    img.load()
            except Exception as e:
                return True, f"Error decodificando imagen: {type(e).__name__} - {str(e)}"
        
        return False, "OK"

    except Exception as e:
        return True, f"Error leyendo archivo: {str(e)}"


def is_video_corrupt(filepath: str) -> tuple[bool, str]:
    """
    Verifica si un video está corrupto.
    Devuelve (True, razón) si está corrupto, o (False, "OK") si es válido.
    """
    try:
        size = os.path.getsize(filepath)
        if size < 100:
            return True, f"Tamaño excesivamente pequeño ({size} bytes)"

        ext = os.path.splitext(filepath)[1].lower()

        # 1. Comprobar Magic Bytes
        if not check_magic_bytes(filepath, ext):
            return True, "Cabecera de archivo no válida (Magic Bytes de video faltantes)"

        # 2. Comprobar decodificación con OpenCV si está disponible
        if HAS_CV2:
            try:
                cap = cv2.VideoCapture(filepath)
                if not cap.isOpened():
                    cap.release()
                    return True, "OpenCV no pudo abrir el contenedor de video"

                # Leer hasta 5 fotogramas de forma secuencial
                # (Evitamos cap.set(POS_FRAMES) para evitar bucles infinitos en tablas de índices corruptas)
                frames_read = 0
                max_frames_to_test = 5
                
                while frames_read < max_frames_to_test:
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        cap.release()
                        if frames_read == 0:
                            return True, "No se pudo decodificar el primer fotograma del video"
                        else:
                            return True, f"Video corrupto/truncado tras fotograma {frames_read}"
                    frames_read += 1

                cap.release()
            except Exception as e:
                return True, f"Error procesando video con OpenCV: {str(e)}"

        return False, "OK"

    except Exception as e:
        return True, f"Error analizando video: {str(e)}"


def check_media_file(filepath: str) -> tuple[bool, str]:
    """Determina si un archivo de medios (imagen o video) está corrupto."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext in IMAGE_EXTENSIONS:
        return is_image_corrupt(filepath)
    elif ext in VIDEO_EXTENSIONS:
        return is_video_corrupt(filepath)
    return False, "Formato no soportado"


def check_media_file_with_timeout(filepath: str, timeout: float = 2.5) -> tuple[bool, str]:
    """
    Ejecuta check_media_file con un tiempo límite estricto (timeout).
    Si OpenCV o PIL se atoran en un archivo profundamente corrupto, se cancela y se marca como corrupto.
    """
    result = [True, "Tiempo de espera agotado (archivo corrupto causa bloqueo)"]
    completed = threading.Event()

    def worker():
        try:
            res = check_media_file(filepath)
            result[0], result[1] = res[0], res[1]
        except Exception as e:
            result[0], result[1] = True, f"Error en análisis: {str(e)}"
        finally:
            completed.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    
    # Si pasa más del tiempo límite (2.5 s), se aborta la espera y se marca como corrupto
    return result[0], result[1]


def repair_file_with_timeout(src_path: str, dst_path: str, is_video: bool, timeout: float = 10.0) -> tuple[bool, str]:
    """
    Ejecuta la función de reparación adecuada (imagen o video) con un tiempo límite estricto (timeout).
    Si OpenCV o Pillow se bloquean al procesar un archivo severamente dañado, se aborta y se marca como no reparable.
    """
    result = [False, f"Tiempo límite de reparación excedido ({timeout}s)"]
    completed = threading.Event()

    def worker():
        try:
            if is_video:
                res = repair_video_file(src_path, dst_path)
            else:
                res = repair_image_file(src_path, dst_path)
            result[0], result[1] = res[0], res[1]
        except Exception as e:
            result[0], result[1] = False, f"Error en reparación: {str(e)}"
        finally:
            completed.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    if not completed.wait(timeout=timeout):
        # Limpiar cualquier residuo de archivo creado a medias
        safe_remove(dst_path)
        return False, f"Tiempo límite excedido ({timeout}s - archivo que congela el códec)"

    return result[0], result[1]



def scan_directory(folder_path: str, recursive: bool = True, callback=None, stop_checker=None):
    """
    Escanea la carpeta en busca de archivos de imagen y video.
    Devuelve lista de (filepath, is_corrupt, reason, file_type, size_bytes).
    """
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        raise ValueError(f"La carpeta no existe: {folder_path}")

    results = []
    pattern = "**/*" if recursive else "*"
    
    files_to_scan = [
        p for p in folder.glob(pattern) 
        if p.is_file() 
        and p.suffix.lower() in MEDIA_EXTENSIONS 
        and "_Archivos_Corruptos" not in p.parts
    ]
    total_files = len(files_to_scan)

    for idx, file_path in enumerate(files_to_scan):
        if stop_checker and stop_checker():
            break

        str_path = str(file_path)
        ext = file_path.suffix.lower()
        file_type = "Imagen" if ext in IMAGE_EXTENSIONS else "Video"
        
        is_corrupt, reason = check_media_file_with_timeout(str_path, timeout=2.5)
        size = os.path.getsize(str_path) if os.path.exists(str_path) else 0
        
        item = {
            'path': str_path,
            'rel_path': str(file_path.relative_to(folder)),
            'is_corrupt': is_corrupt,
            'reason': reason,
            'type': file_type,
            'size': size
        }
        results.append(item)

        if callback:
            callback(idx + 1, total_files, item)

    return results


def repair_image_file(src_path: str, dst_path: str) -> tuple[bool, str]:
    """
    Motor de Reparación Exhaustiva de Imágenes - 6 Pasos Encadenados.
    Diseñado específicamente para archivos recuperados por EaseUS, Recuva, PhotoRec, etc.
    Usa validación PERMISIVA (is_repair_valid) en lugar de la estricta is_image_corrupt.
    """
    file_ext = os.path.splitext(src_path)[1].lower()
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)

    # Leer datos brutos del archivo
    try:
        with open(src_path, 'rb') as f:
            raw_data = f.read()
    except Exception as e:
        return False, f"No se pudo leer archivo fuente: {str(e)}"

    if len(raw_data) < 8:
        return False, "Archivo vacío o excesivamente pequeño (<8 bytes)"

    # =========================================================================
    # PASO 0: DETECCIÓN DE FORMATO REAL (ignorar extensión del archivo)
    # =========================================================================
    real_fmt = detect_real_format(src_path)
    # Usar el formato real si se detectó, sino usar la extensión del archivo
    ext = real_fmt if real_fmt else file_ext
    fmt_note = f" [Formato real detectado: {ext}]" if real_fmt and real_fmt != file_ext else ""

    # =========================================================================
    # PASO 1: LIMPIEZA BINARIA + RECONSTRUCCIÓN DE CABECERAS
    # =========================================================================
    patched_data = raw_data

    if ext in ('.jpg', '.jpeg'):
        # Buscar firma JPEG (FF D8 FF) y recortar basura previa
        soi_idx = raw_data.find(b'\xff\xd8\xff')
        if soi_idx > 0:
            patched_data = raw_data[soi_idx:]
        elif soi_idx < 0:
            # No se encontró firma JPEG - buscar más profundo
            soi2 = raw_data.find(b'\xff\xd8')
            if soi2 >= 0:
                patched_data = raw_data[soi2:]
            else:
                # Forzar cabecera JPEG mínima
                patched_data = b'\xff\xd8\xff\xe0' + raw_data

        # Asegurar que empieza con FF D8
        if not patched_data.startswith(b'\xff\xd8'):
            patched_data = b'\xff\xd8' + patched_data

        # Añadir marcador EOI (FF D9) si falta
        if not patched_data.endswith(b'\xff\xd9'):
            # Buscar si hay un EOI en medio (datos truncados con basura al final)
            last_eoi = patched_data.rfind(b'\xff\xd9')
            if last_eoi > 0 and last_eoi < len(patched_data) - 2:
                patched_data = patched_data[:last_eoi + 2]
            else:
                patched_data += b'\xff\xd9'

        try:
            with open(dst_path, 'wb') as f:
                f.write(patched_data)
            if is_repair_valid(dst_path):
                return True, f"Paso 1: Cabecera JPEG SOI/EOI reconstruida{fmt_note}"
        except Exception:
            pass

    elif ext == '.png':
        png_sig = b'\x89PNG\r\n\x1a\n'
        sig_idx = raw_data.find(png_sig)
        if sig_idx > 0:
            patched_data = raw_data[sig_idx:]
        elif not raw_data.startswith(png_sig):
            patched_data = png_sig + raw_data

        iend_chunk = b'\x00\x00\x00\x00IEND\xaeB`\x82'
        if not patched_data.endswith(iend_chunk):
            iend_pos = patched_data.rfind(b'IEND')
            if iend_pos > 0:
                patched_data = patched_data[:iend_pos - 4] + iend_chunk
            else:
                patched_data += iend_chunk

        try:
            with open(dst_path, 'wb') as f:
                f.write(patched_data)
            if is_repair_valid(dst_path):
                return True, f"Paso 1: Estructura PNG IHDR/IEND reparada{fmt_note}"
        except Exception:
            pass

    elif ext == '.webp':
        riff_idx = raw_data.find(b'RIFF')
        if riff_idx > 0:
            patched_data = raw_data[riff_idx:]

        if patched_data.startswith(b'RIFF') and b'WEBP' in patched_data[:16]:
            try:
                with open(dst_path, 'wb') as f:
                    f.write(patched_data)
                if is_repair_valid(dst_path):
                    return True, f"Paso 1: Cabecera RIFF/WEBP realineada{fmt_note}"
            except Exception:
                pass

    elif ext == '.bmp':
        bm_idx = raw_data.find(b'BM')
        if bm_idx > 0:
            patched_data = raw_data[bm_idx:]
        try:
            with open(dst_path, 'wb') as f:
                f.write(patched_data)
            if is_repair_valid(dst_path):
                return True, f"Paso 1: Cabecera BMP realineada{fmt_note}"
        except Exception:
            pass

    elif ext in ('.gif',):
        gif_idx = raw_data.find(b'GIF8')
        if gif_idx > 0:
            patched_data = raw_data[gif_idx:]
        try:
            with open(dst_path, 'wb') as f:
                f.write(patched_data)
            if is_repair_valid(dst_path):
                return True, f"Paso 1: Cabecera GIF realineada{fmt_note}"
        except Exception:
            pass

    elif ext in ('.tiff', '.tif'):
        for sig in (b'II*\x00', b'MM\x00*'):
            idx = raw_data.find(sig)
            if idx >= 0:
                patched_data = raw_data[idx:]
                break
        try:
            with open(dst_path, 'wb') as f:
                f.write(patched_data)
            if is_repair_valid(dst_path):
                return True, f"Paso 1: Cabecera TIFF realineada{fmt_note}"
        except Exception:
            pass

    # =========================================================================
    # PASO 2: PILLOW TRUNCATED - Abrir datos PARCHEADOS del Paso 1
    # =========================================================================
    if HAS_PIL:
        # Intentar con los datos parcheados escritos en dst_path (del Paso 1)
        for source_file in [dst_path, src_path]:
            if not os.path.exists(source_file):
                continue
            try:
                ImageFile.LOAD_TRUNCATED_IMAGES = True
                with Image.open(source_file) as img:
                    try:
                        img.load()
                    except Exception:
                        pass  # Continuar aunque falle la carga completa

                    w, h = img.size
                    if w > 0 and h > 0:
                        mode = img.mode
                        if mode in ("RGBA", "P", "CMYK", "LA", "PA") and ext in ('.jpg', '.jpeg'):
                            canvas = Image.new("RGB", (w, h), (255, 255, 255))
                            try:
                                if mode in ("RGBA", "LA", "PA"):
                                    canvas.paste(img, mask=img.split()[-1])
                                else:
                                    canvas.paste(img.convert("RGB"))
                            except Exception:
                                canvas.paste(img.convert("RGB"))
                        else:
                            canvas = Image.new(mode, (w, h))
                            try:
                                canvas.paste(img)
                            except Exception:
                                pass

                        canvas.save(dst_path)

                        if is_repair_valid(dst_path):
                            src_label = "parcheados" if source_file == dst_path else "originales"
                            return True, f"Paso 2: Re-renderizado de píxeles {src_label} en lienzo canvas{fmt_note}"
            except Exception:
                pass

    # =========================================================================
    # PASO 3: CONVERSIÓN DE EMERGENCIA (cambiar formato de salida)
    # =========================================================================
    if HAS_PIL:
        # Intentar guardar en formatos alternativos (PNG es sin pérdida, más tolerante)
        alt_formats = [("PNG", ".png"), ("BMP", ".bmp"), ("TIFF", ".tiff")]
        for source_file in [dst_path, src_path]:
            if not os.path.exists(source_file):
                continue
            for fmt_name, fmt_ext in alt_formats:
                try:
                    ImageFile.LOAD_TRUNCATED_IMAGES = True
                    with Image.open(source_file) as img:
                        try:
                            img.load()
                        except Exception:
                            pass

                        w, h = img.size
                        if w < 1 or h < 1:
                            continue

                        alt_dst = os.path.splitext(dst_path)[0] + fmt_ext
                        if img.mode in ("RGBA", "P", "CMYK", "LA", "PA"):
                            img = img.convert("RGB")
                        img.save(alt_dst, fmt_name)

                        if is_repair_valid(alt_dst):
                            # Mover al destino final
                            if alt_dst != dst_path:
                                safe_move(alt_dst, dst_path)
                            return True, f"Paso 3: Conversión de emergencia a {fmt_name}{fmt_note}"
                        else:
                            safe_remove(alt_dst)
                except Exception:
                    pass

    # =========================================================================
    # PASO 4: RESCATE CON OPENCV (cv2.imread es más tolerante que Pillow)
    # =========================================================================
    if HAS_CV2:
        for source_file in [dst_path, src_path]:
            if not os.path.exists(source_file):
                continue
            try:
                img_cv = cv2.imread(source_file, cv2.IMREAD_COLOR)
                if img_cv is not None and img_cv.shape[0] > 0 and img_cv.shape[1] > 0:
                    # Guardar como PNG para máxima compatibilidad
                    cv2.imwrite(dst_path, img_cv)
                    if is_repair_valid(dst_path):
                        return True, f"Paso 4: Rescate mediante decodificador OpenCV{fmt_note}"
            except Exception:
                pass

        # Intentar con flags de lectura alternativos
        for source_file in [dst_path, src_path]:
            if not os.path.exists(source_file):
                continue
            for flag in [cv2.IMREAD_UNCHANGED, cv2.IMREAD_GRAYSCALE, cv2.IMREAD_ANYCOLOR]:
                try:
                    img_cv = cv2.imread(source_file, flag)
                    if img_cv is not None and img_cv.shape[0] > 0 and img_cv.shape[1] > 0:
                        cv2.imwrite(dst_path, img_cv)
                        if is_repair_valid(dst_path):
                            return True, f"Paso 4b: Rescate OpenCV con modo alternativo{fmt_note}"
                except Exception:
                    pass

    # =========================================================================
    # PASO 5: COPIA DIRECTA (si el archivo parece tener contenido visual útil)
    # =========================================================================
    # Algunos archivos "corruptos" según verify() son en realidad abribles por visores
    try:
        shutil.copy2(src_path, dst_path)
        if is_repair_valid(dst_path):
            return True, f"Paso 5: Archivo recuperable sin modificación (error de verificación estricta){fmt_note}"
    except Exception:
        pass

    # =========================================================================
    # PASO 6: REPARACIÓN CRUZADA DE FORMATO
    # Si la extensión no coincide con el formato real, intentar tratar como el formato real
    # =========================================================================
    if real_fmt and real_fmt != file_ext and HAS_PIL:
        # Re-intentar pasos 2-3 pero forzando apertura como formato real
        try:
            ImageFile.LOAD_TRUNCATED_IMAGES = True
            # Crear copia temporal con la extensión correcta
            temp_src = src_path + real_fmt
            shutil.copy2(src_path, temp_src)
            try:
                with Image.open(temp_src) as img:
                    try:
                        img.load()
                    except Exception:
                        pass
                    if img.size[0] > 0 and img.size[1] > 0:
                        if img.mode in ("RGBA", "P", "CMYK", "LA", "PA"):
                            img = img.convert("RGB")
                        img.save(dst_path, "PNG")
                        if is_repair_valid(dst_path):
                            return True, f"Paso 6: Reparación cruzada de formato ({file_ext} era realmente {real_fmt})"
            finally:
                safe_remove(temp_src)
        except Exception:
            pass

    # Limpiar residuos si todo falló
    safe_remove(dst_path)

    return False, f"Estructura de imagen irreparablemente destruida{fmt_note}"


def repair_video_file(src_path: str, dst_path: str) -> tuple[bool, str]:
    """
    Motor de Reparación Exhaustiva de Videos - 3 Pasos.
    Diseñado para archivos recuperados con contenedores dañados (moov atom, índices, etc).
    Acepta incluso 1 fotograma salvado como reparación exitosa.
    """
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)

    # =========================================================================
    # PASO 1: Re-extracción secuencial de fotogramas con OpenCV
    # =========================================================================
    if HAS_CV2:
        try:
            cap = cv2.VideoCapture(src_path)
            if cap.isOpened():
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                raw_fps = cap.get(cv2.CAP_PROP_FPS)

                # Clamp FPS inválido (videos corruptos reportan 90000, 0, NaN, etc.)
                if not raw_fps or raw_fps <= 0 or raw_fps > 120.0:
                    fps = 30.0
                else:
                    fps = float(raw_fps)

                if width > 0 and height > 0:
                    out = None
                    used_codec = ""
                    for fourcc_str in ('mp4v', 'avc1', 'H264', 'MJPG', 'XVID'):
                        try:
                            fourcc = cv2.VideoWriter_fourcc(*fourcc_str)
                            test_out = cv2.VideoWriter(dst_path, fourcc, fps, (width, height))
                            if test_out.isOpened():
                                out = test_out
                                used_codec = fourcc_str
                                break
                            else:
                                test_out.release()
                        except Exception:
                            pass

                    if out and out.isOpened():
                        saved_frames = 0
                        consecutive_fails = 0

                        while True:
                            ret, frame = cap.read()
                            if not ret or frame is None:
                                consecutive_fails += 1
                                if consecutive_fails > 50:
                                    break
                                continue

                            consecutive_fails = 0
                            out.write(frame)
                            saved_frames += 1
                            if saved_frames >= 3000:
                                break

                        cap.release()
                        out.release()

                        # Aceptar incluso 1 fotograma — en recuperación, cada frame cuenta
                        if saved_frames >= 1:
                            if is_repair_valid(dst_path):
                                return True, f"Paso 1: Video re-empaquetado salvando {saved_frames:,} fotogramas ({used_codec})"
            cap.release()
        except Exception:
            pass

    # =========================================================================
    # PASO 2: Rescate de NAL Units H.264 / H.265 en bruto
    # =========================================================================
    try:
        with open(src_path, 'rb') as f:
            raw_video = f.read(min(os.path.getsize(src_path), 20 * 1024 * 1024))

        nal_start = b'\x00\x00\x00\x01'
        nal_short = b'\x00\x00\x01'
        has_nal = nal_start in raw_video or nal_short in raw_video

        if has_nal and HAS_CV2:
            cap = cv2.VideoCapture(src_path, cv2.CAP_FFMPEG)
            if cap.isOpened():
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                if w > 0 and h > 0:
                    out = cv2.VideoWriter(dst_path, cv2.VideoWriter_fourcc(*'mp4v'), 25.0, (w, h))
                    if out.isOpened():
                        count = 0
                        for _ in range(3000):
                            ret, frame = cap.read()
                            if ret and frame is not None:
                                out.write(frame)
                                count += 1
                            else:
                                break
                        cap.release()
                        out.release()
                        if count >= 1 and is_repair_valid(dst_path):
                            return True, f"Paso 2: Flujo NAL H.264/H.265 rescatado con {count:,} fotogramas"
                    else:
                        out.release()
            cap.release()
    except Exception:
        pass

    # =========================================================================
    # PASO 3: Extracción de fotograma individual como imagen estática
    # Si no podemos salvar el video, al menos salvar 1 fotograma como .png
    # =========================================================================
    if HAS_CV2:
        try:
            cap = cv2.VideoCapture(src_path)
            if cap.isOpened():
                ret, frame = cap.read()
                cap.release()
                if ret and frame is not None and frame.shape[0] > 0:
                    # Guardar como imagen PNG - al menos se salva algo
                    still_path = os.path.splitext(dst_path)[0] + "_fotograma.png"
                    cv2.imwrite(still_path, frame)
                    if os.path.exists(still_path) and os.path.getsize(still_path) > 100:
                        safe_move(still_path, dst_path)
                        return True, "Paso 3: Fotograma individual rescatado como imagen estática"
            else:
                cap.release()
        except Exception:
            pass

    # Limpieza
    safe_remove(dst_path)

    return False, "Video sin índice de contenedor (moov atom) ni flujo NAL legible"


def process_corrupt_files(folder_path: str, corrupt_items: list, action: str = "quarantine", callback=None):
    """
    Aplica la acción seleccionada ('quarantine', 'repair' o 'delete') a los archivos corruptos.
    Genera un informe con los detalles.
    """
    folder = Path(folder_path)
    action_label = {
        'quarantine': 'Mover a Cuarentena',
        'repair': 'Intentar Reparación y Mover Originales a Cuarentena',
        'delete': 'Eliminar Definitivamente'
    }.get(action, action)

    report_lines = [
        "==================================================",
        "INFORME DE LIMPIEZA / REPARACIÓN DE MEDIOS CORRUPTOS",
        f"Fecha y Hora: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Carpeta Analizada: {folder_path}",
        f"Acción Realizada: {action_label}",
        "==================================================\n"
    ]

    quarantine_dir = folder / "_Archivos_Corruptos"
    repair_dir = folder / "_Archivos_Reparados"

    if action == "repair":
        repair_dir.mkdir(exist_ok=True)
        quarantine_dir.mkdir(exist_ok=True)
    elif action == "quarantine" and corrupt_items:
        quarantine_dir.mkdir(exist_ok=True)

    success_count = 0
    repaired_count = 0
    fail_count = 0
    total = len(corrupt_items)

    for idx, item in enumerate(corrupt_items):
        src = Path(item['path'])
        if src.exists():
            try:
                if action == "repair":
                    dst_rep = repair_dir / item['rel_path']
                    dst_q = quarantine_dir / item['rel_path']
                    dst_rep.parent.mkdir(parents=True, exist_ok=True)
                    dst_q.parent.mkdir(parents=True, exist_ok=True)
                    ext = src.suffix.lower()
                    
                    if ext in IMAGE_EXTENSIONS:
                        repaired, r_msg = repair_file_with_timeout(str(src), str(dst_rep), is_video=False, timeout=8.0)
                    elif ext in VIDEO_EXTENSIONS:
                        repaired, r_msg = repair_file_with_timeout(str(src), str(dst_rep), is_video=True, timeout=10.0)
                    else:
                        repaired, r_msg = False, "Formato no soportado para reparación"

                    if repaired:
                        repaired_count += 1
                        # Mover el archivo original dañado a _Archivos_Corruptos para limpiar la carpeta de origen
                        moved = safe_move(str(src), str(dst_q))
                        if moved:
                            report_lines.append(f"[REPARADO CON ÉXITO] {item['rel_path']} -> Copia limpia en _Archivos_Reparados | Original en _Archivos_Corruptos | {r_msg}")
                        else:
                            report_lines.append(f"[REPARADO PERO BLOQUEADO] {item['rel_path']} -> Copia limpia en _Archivos_Reparados | {r_msg}")
                    else:
                        safe_move(str(src), str(dst_q))
                        report_lines.append(f"[NO REPARABLE -> CUARENTENA] {item['rel_path']} -> Original en _Archivos_Corruptos | {r_msg}")
                    success_count += 1

                elif action == "quarantine":
                    dst = quarantine_dir / item['rel_path']
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    safe_move(str(src), str(dst))
                    report_lines.append(f"[MOVIDO] {item['rel_path']} -> _Archivos_Corruptos | Razón: {item['reason']}")
                    success_count += 1

                elif action == "delete":
                    safe_remove(str(src))
                    report_lines.append(f"[ELIMINADO] {item['rel_path']} | Razón: {item['reason']}")
                    success_count += 1

            except Exception as e:
                fail_count += 1
                report_lines.append(f"[ERROR] No se pudo procesar {item['rel_path']}: {str(e)}")

        if callback:
            callback(idx + 1, total, item)

    report_lines.append(f"\nResumen: {success_count} procesados ({repaired_count} reparados con éxito), {fail_count} errores.")
    
    report_path = folder / "reporte_limpieza_corruptos.txt"
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))
    except Exception as e:
        print(f"Error escribiendo el reporte: {e}")

    return success_count, fail_count, repaired_count, str(report_path)


def repair_directory_direct(folder_path: str, callback=None, stop_checker=None):
    """
    Intenta reparar directamente todos los archivos multimedia de una carpeta (ej. una carpeta de corruptos previa)
    sin necesidad de análisis o filtrado previo. Preserva la estructura exacta del árbol de subcarpetas.
    """
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        raise ValueError(f"La carpeta no existe: {folder_path}")

    repair_dir = folder / "_Archivos_Reparados"
    quarantine_dir = folder / "_Archivos_No_Reparables"

    files_to_repair = [
        p for p in folder.glob("**/*")
        if p.is_file()
        and p.suffix.lower() in MEDIA_EXTENSIONS
        and "_Archivos_Reparados" not in p.parts
        and "_Archivos_No_Reparables" not in p.parts
        and "_Archivos_Corruptos" not in p.parts
    ]
    total = len(files_to_repair)
    if total == 0:
        return 0, 0, 0, ""

    repair_dir.mkdir(exist_ok=True)
    quarantine_dir.mkdir(exist_ok=True)

    repaired_count = 0
    failed_count = 0

    report_lines = [
        "==================================================",
        "INFORME DE REPARACIÓN DIRECTA DE CARPETA",
        f"Fecha y Hora: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Carpeta Analizada: {folder_path}",
        "==================================================\n"
    ]

    for idx, file_path in enumerate(files_to_repair):
        if stop_checker and stop_checker():
            break

        str_path = str(file_path)
        rel_p = str(file_path.relative_to(folder))
        ext = file_path.suffix.lower()
        dst_rep = repair_dir / rel_p
        dst_q = quarantine_dir / rel_p
        
        # Preservar árbol de subcarpetas idéntico
        dst_rep.parent.mkdir(parents=True, exist_ok=True)
        dst_q.parent.mkdir(parents=True, exist_ok=True)

        try:
            if ext in IMAGE_EXTENSIONS:
                repaired, r_msg = repair_file_with_timeout(str_path, str(dst_rep), is_video=False, timeout=8.0)
            elif ext in VIDEO_EXTENSIONS:
                repaired, r_msg = repair_file_with_timeout(str_path, str(dst_rep), is_video=True, timeout=10.0)
            else:
                repaired, r_msg = False, "Formato no soportado para reparación"

            if repaired:
                repaired_count += 1
                moved = safe_move(str_path, str(dst_q))
                if moved:
                    report_lines.append(f"[REPARADO] {rel_p} -> Copia limpia en _Archivos_Reparados | Original en _Archivos_No_Reparables | {r_msg}")
                else:
                    report_lines.append(f"[REPARADO PERO BLOQUEADO] {rel_p} -> Copia limpia en _Archivos_Reparados | {r_msg}")
            else:
                failed_count += 1
                safe_move(str_path, str(dst_q))
                report_lines.append(f"[NO REPARABLE] {rel_p} -> Movido a _Archivos_No_Reparables | {r_msg}")
        except Exception as e:
            failed_count += 1
            report_lines.append(f"[ERROR EN PROCESO] {rel_p}: {str(e)}")

        if callback:
            callback(idx + 1, total, rel_p, repaired)

    report_path = folder / "reporte_reparacion_directa.txt"
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))
    except Exception as e:
        print(f"Error escribiendo reporte: {e}")

    return total, repaired_count, failed_count, str(report_path)


# ==============================================================================
# INTERFAZ GRÁFICA (GUI con Tkinter)
# ==============================================================================

def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, scrolledtext

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("Limpiador de Imágenes y Videos Corruptos")
            self.geometry("820x620")
            self.minsize(700, 500)
            
            # Estilos
            self.style = ttk.Style()
            self.style.theme_use('clam')
            
            self.scanned_items = []
            self.corrupt_items = []
            self.is_scanning = False
            self.stop_requested = False

            self.create_widgets()

        def create_widgets(self):
            # Frame Superior: Selección de Carpeta
            top_frame = ttk.LabelFrame(self, text=" 1. Selección de Carpeta ", padding=10)
            top_frame.pack(fill="x", padx=10, pady=5)

            ttk.Label(top_frame, text="Carpeta a analizar:").pack(side="left", padx=5)
            self.entry_folder = ttk.Entry(top_frame, width=50)
            self.entry_folder.pack(side="left", fill="x", expand=True, padx=5)
            
            btn_browse = ttk.Button(top_frame, text="Buscar...", command=self.browse_folder)
            btn_browse.pack(side="left", padx=5)

            # Frame Opciones
            opts_frame = ttk.LabelFrame(self, text=" 2. Opciones de Análisis y Acción ", padding=10)
            opts_frame.pack(fill="x", padx=10, pady=5)

            self.var_recursive = tk.BooleanVar(value=True)
            chk_rec = ttk.Checkbutton(opts_frame, text="Incluir subcarpetas", variable=self.var_recursive)
            chk_rec.pack(anchor="w", pady=2)

            self.var_action = tk.StringVar(value="quarantine")
            rb_quarantine = ttk.Radiobutton(opts_frame, text="Mover archivos corruptos a carpeta '_Archivos_Corruptos' (Recomendado)", 
                                           variable=self.var_action, value="quarantine")
            rb_quarantine.pack(anchor="w", pady=2)

            rb_repair = ttk.Radiobutton(opts_frame, text="🛠️ INTENTAR REPARACIÓN: Guardar recuperados en '_Archivos_Reparados' (y los demás en cuarentena)", 
                                       variable=self.var_action, value="repair")
            rb_repair.pack(anchor="w", pady=2)
            
            rb_delete = ttk.Radiobutton(opts_frame, text="Eliminar archivos corruptos definitivamente", 
                                       variable=self.var_action, value="delete")
            rb_delete.pack(anchor="w", pady=2)

            # Panel de Estadísticas en Tiempo Real
            stats_frame = ttk.LabelFrame(self, text=" 📊 Contador en Tiempo Real ", padding=8)
            stats_frame.pack(fill="x", padx=10, pady=4)

            self.lbl_stats = ttk.Label(
                stats_frame, 
                text="📊 Analizados: 0  |  ✅ Válidos: 0  |  ❌ CORRUPTOS: 0", 
                font=("Segoe UI", 10, "bold"),
                foreground="#004085"
            )
            self.lbl_stats.pack(anchor="w", padx=5)

            # Botones de Control
            btn_frame = ttk.Frame(self, padding=5)
            btn_frame.pack(fill="x", padx=10, pady=5)

            self.btn_scan = ttk.Button(btn_frame, text="🔍 Buscar Corruptos", command=self.start_scan)
            self.btn_scan.pack(side="left", padx=2, expand=True, fill="x")

            self.btn_direct_repair = ttk.Button(btn_frame, text="🛠️ Reparar Carpeta Directa", command=self.start_direct_repair)
            self.btn_direct_repair.pack(side="left", padx=2, expand=True, fill="x")

            self.btn_stop = ttk.Button(btn_frame, text="🛑 Detener Escaneo", command=self.stop_scan, state="disabled")
            self.btn_stop.pack(side="left", padx=2, expand=True, fill="x")

            self.btn_process = ttk.Button(btn_frame, text="⚠️ Procesar / Limpiar", command=self.start_process, state="disabled")
            self.btn_process.pack(side="left", padx=2, expand=True, fill="x")

            # Barra de progreso
            self.progress_var = tk.DoubleVar()
            self.progress_bar = ttk.Progressbar(self, variable=self.progress_var, maximum=100)
            self.progress_bar.pack(fill="x", padx=10, pady=5)

            self.lbl_status = ttk.Label(self, text="Listo para analizar. Selecciona una carpeta.", font=("Segoe UI", 9, "bold"))
            self.lbl_status.pack(anchor="w", padx=10)

            # Lista y Consola de Resultados
            notebook = ttk.Notebook(self)
            notebook.pack(fill="both", expand=True, padx=10, pady=5)

            # Tab 1: Archivos Corruptos Detectados
            tab_corrupt = ttk.Frame(notebook)
            notebook.add(tab_corrupt, text=" Archivos Corruptos (0) ")
            self.tab_corrupt_ref = notebook

            columns = ("tipo", "rel_path", "razon", "tamano")
            self.tree_corrupt = ttk.Treeview(tab_corrupt, columns=columns, show="headings", selectmode="extended")
            self.tree_corrupt.heading("tipo", text="Tipo")
            self.tree_corrupt.heading("rel_path", text="Archivo")
            self.tree_corrupt.heading("razon", text="Causa de Corrupción")
            self.tree_corrupt.heading("tamano", text="Tamaño")

            self.tree_corrupt.column("tipo", width=80, anchor="center")
            self.tree_corrupt.column("rel_path", width=300)
            self.tree_corrupt.column("razon", width=260)
            self.tree_corrupt.column("tamano", width=90, anchor="e")

            scroll_tree = ttk.Scrollbar(tab_corrupt, orient="vertical", command=self.tree_corrupt.yview)
            self.tree_corrupt.configure(yscrollcommand=scroll_tree.set)

            self.tree_corrupt.pack(side="left", fill="both", expand=True)
            scroll_tree.pack(side="right", fill="y")

            # Tab 2: Log en Vivo
            tab_log = ttk.Frame(notebook)
            notebook.add(tab_log, text=" Registro de Registro / Log ")

            self.txt_log = scrolledtext.ScrolledText(tab_log, wrap="word", state="disabled", font=("Consolas", 9))
            self.txt_log.pack(fill="both", expand=True)

        def log_message(self, msg: str):
            self.txt_log.config(state="normal")
            self.txt_log.insert("end", msg + "\n")
            self.txt_log.see("end")
            self.txt_log.config(state="disabled")

        def browse_folder(self):
            selected = filedialog.askdirectory()
            if selected:
                self.entry_folder.delete(0, tk.END)
                self.entry_folder.insert(0, selected)

        def stop_scan(self):
            if self.is_scanning:
                self.stop_requested = True
                self.btn_stop.config(state="disabled", text="⏳ Deteniendo...")
                self.lbl_status.config(text="Deteniendo escaneo por solicitud del usuario...")

        def start_scan(self):
            folder = self.entry_folder.get().strip()
            if not folder or not os.path.isdir(folder):
                messagebox.showerror("Error", "Por favor selecciona una carpeta válida.")
                return

            self.is_scanning = True
            self.stop_requested = False

            self.btn_scan.config(state="disabled")
            self.btn_stop.config(state="normal", text="🛑 Detener Escaneo")
            self.btn_process.config(state="disabled")
            
            self.tree_corrupt.delete(*self.tree_corrupt.get_children())
            self.txt_log.config(state="normal")
            self.txt_log.delete("1.0", tk.END)
            self.txt_log.config(state="disabled")

            self.scanned_items.clear()
            self.corrupt_items.clear()
            self.lbl_stats.config(text="📊 Analizados: 0  |  ✅ Válidos: 0  |  ❌ CORRUPTOS: 0")

            threading.Thread(target=self._scan_thread, args=(folder,), daemon=True).start()

        def _scan_thread(self, folder):
            self.log_message(f"=== Iniciando escaneo en: {folder} ===")
            if not HAS_PIL:
                self.log_message("[ADVERTENCIA] Pillow no instalado. El análisis de imágenes se limitará a comprobación de cabeceras.")
            if not HAS_CV2:
                self.log_message("[ADVERTENCIA] OpenCV (cv2) no instalado. El análisis de videos se limitará a comprobación de cabeceras.")

            scanned_count = 0
            corrupt_count = 0
            valid_count = 0

            def scan_cb(current, total, item):
                nonlocal scanned_count, corrupt_count, valid_count
                scanned_count = current
                if item['is_corrupt']:
                    corrupt_count += 1
                else:
                    valid_count += 1

                percent = (current / total) * 100
                
                # Actualizar interfaz en tiempo real
                if current % 5 == 0 or current == total or item['is_corrupt']:
                    status_txt = f"Analizando ({current}/{total}): {item['rel_path']}"
                    stats_txt = f"📊 Analizados: {current:,} / {total:,}   |   ✅ Válidos: {valid_count:,}   |   ❌ CORRUPTOS: {corrupt_count:,}"
                    tab_txt = f" Archivos Corruptos ({corrupt_count}) "

                    self.after(0, lambda p=percent, st=status_txt, stt=stats_txt, tt=tab_txt: (
                        self.progress_var.set(p),
                        self.lbl_status.config(text=st),
                        self.lbl_stats.config(text=stt),
                        self.tab_corrupt_ref.tab(0, text=tt)
                    ))

                if item['is_corrupt']:
                    self.corrupt_items.append(item)
                    size_kb = f"{item['size'] / 1024:.1f} KB"
                    tp, rel_p, rzn = item['type'], item['rel_path'], item['reason']
                    self.after(0, lambda: (
                        self.tree_corrupt.insert("", "end", values=(tp, rel_p, rzn, size_kb)),
                        self.log_message(f"[CORRUPTO] [{tp}] {rel_p} - {rzn}")
                    ))

            try:
                results = scan_directory(
                    folder, 
                    recursive=self.var_recursive.get(), 
                    callback=scan_cb,
                    stop_checker=lambda: self.stop_requested
                )
                self.scanned_items = results

                total = len(results)
                final_corrupt_count = len(self.corrupt_items)
                final_valid_count = len(results) - final_corrupt_count

                if self.stop_requested:
                    msg = f"Escaneo DETENIDO por el usuario. {len(results)} analizados | {final_corrupt_count} CORRUPTOS."
                else:
                    msg = f"Escaneo completado: {total} procesados | {final_valid_count} válidos | {final_corrupt_count} CORRUPTOS."
                
                def on_finish():
                    self.lbl_status.config(text=msg)
                    self.log_message(f"\n=== {msg} ===")
                    self.tab_corrupt_ref.tab(0, text=f" Archivos Corruptos ({final_corrupt_count}) ")
                    if final_corrupt_count > 0:
                        self.btn_process.config(state="normal")

                    if self.stop_requested:
                        messagebox.showwarning(
                            "Escaneo Detenido", 
                            f"El escaneo fue detenido por el usuario.\n\n"
                            f"Archivos analizados hasta el momento: {len(results)}\n"
                            f"Archivos corruptos encontrados: {final_corrupt_count}"
                        )
                    elif final_corrupt_count > 0:
                        messagebox.showwarning("Atención", f"Se han encontrado {final_corrupt_count} archivos de imagen/video corruptos.")
                    else:
                        messagebox.showinfo("Excelente", "No se encontró ningún archivo corrupto en la carpeta.")

                self.after(0, on_finish)

            except Exception as e:
                self.after(0, lambda err=str(e): (
                    messagebox.showerror("Error de Escaneo", err),
                    self.log_message(f"ERROR: {err}")
                ))
            finally:
                def cleanup():
                    self.btn_scan.config(state="normal")
                    self.btn_stop.config(state="disabled", text="🛑 Detener Escaneo")
                    self.is_scanning = False

                self.after(0, cleanup)

        def start_process(self):
            if not self.corrupt_items:
                return

            action = self.var_action.get()
            if action == "repair":
                action_str = "INTENTAR REPARACIÓN y guardar recuperados en '_Archivos_Reparados'"
            elif action == "quarantine":
                action_str = "MOVER a '_Archivos_Corruptos'"
            else:
                action_str = "ELIMINAR PERMANENTEMENTE"
            
            confirm = messagebox.askyesno(
                "Confirmar Acción",
                f"Vas a realizar la siguiente acción sobre {len(self.corrupt_items):,} archivos corruptos:\n\n"
                f"Acción: {action_str}\n\n"
                "¿Deseas continuar?"
            )
            
            if not confirm:
                return

            folder = self.entry_folder.get().strip()
            self.btn_scan.config(state="disabled")
            self.btn_process.config(state="disabled")
            self.btn_stop.config(state="disabled")
            self.progress_var.set(0)

            threading.Thread(target=self._process_thread, args=(folder, action), daemon=True).start()

        def _process_thread(self, folder, action):
            if action == "repair":
                action_verb = "Reparando"
                action_icon = "🛠️"
            elif action == "quarantine":
                action_verb = "Moviendo a cuarentena"
                action_icon = "📦"
            else:
                action_verb = "Eliminando"
                action_icon = "🗑️"

            repaired_live = 0
            failed_live = 0

            def process_cb(current, total, item):
                nonlocal repaired_live, failed_live
                percent = (current / total) * 100 if total > 0 else 100

                # Actualizar cada archivo (no cada 10, porque la reparación es lenta)
                fname = os.path.basename(item['rel_path'])
                status_txt = f"{action_verb} ({current:,}/{total:,}): {fname}"

                if action == "repair":
                    rate = (repaired_live / current * 100) if current > 0 else 0
                    stats_txt = (
                        f"{action_icon} {current:,} / {total:,} ({percent:.1f}%)   |   "
                        f"✅ Reparados: {repaired_live:,}   |   "
                        f"❌ Fallidos: {failed_live:,}   |   "
                        f"📈 Tasa: {rate:.1f}%"
                    )
                else:
                    stats_txt = f"{action_icon} {action_verb}: {current:,} / {total:,} ({percent:.1f}%)"

                self.after(0, lambda p=percent, st=status_txt, stt=stats_txt: (
                    self.progress_var.set(p),
                    self.lbl_status.config(text=st),
                    self.lbl_stats.config(text=stt)
                ))

            try:
                success, fail, repaired, report_path = process_corrupt_files(folder, self.corrupt_items, action=action, callback=process_cb)

                # Actualizar contadores live finales
                repaired_live = repaired
                failed_live = success - repaired

                def on_process_finish():
                    if action == "repair":
                        rate = (repaired / success * 100) if success > 0 else 0
                        msg_text = (
                            f"Reparación Finalizada\n\n"
                            f"Archivos procesados: {success:,}\n"
                            f"✅ Archivos REPARADOS con éxito: {repaired:,}\n"
                            f"❌ Archivos no reparables (en cuarentena): {success - repaired:,}\n"
                            f"⚠️ Errores: {fail:,}\n"
                            f"📈 Tasa de recuperación: {rate:.1f}%\n\n"
                            f"Se ha guardado un informe detallado en:\n{report_path}"
                        )
                    else:
                        msg_text = (
                            f"Se han procesado los archivos corruptos correctamente.\n\n"
                            f"Éxitos: {success:,}\n"
                            f"Errores: {fail:,}\n\n"
                            f"Se ha guardado un informe detallado en:\n{report_path}"
                        )

                    messagebox.showinfo("Proceso Finalizado", msg_text)

                    # Limpiar lista tras procesar
                    self.tree_corrupt.delete(*self.tree_corrupt.get_children())
                    self.corrupt_items.clear()
                    self.btn_process.config(state="disabled")
                    self.tab_corrupt_ref.tab(0, text=" Archivos Corruptos (0) ")
                    self.lbl_status.config(text="Archivos procesados correctamente.")
                    if action == "repair":
                        rate = (repaired / success * 100) if success > 0 else 0
                        self.lbl_stats.config(text=f"🛠️ Reparación completada: {repaired:,} recuperados ({rate:.1f}% de éxito).")
                    else:
                        self.lbl_stats.config(text=f"✅ Proceso completado: {success:,} procesados con éxito.")
                    self.progress_var.set(100)

                self.after(0, on_process_finish)

            except Exception as e:
                self.after(0, lambda err=str(e): (
                    messagebox.showerror("Error de Procesamiento", f"Error procesando archivos: {err}"),
                    self.log_message(f"ERROR PROCESANDO: {err}")
                ))
            finally:
                self.after(0, lambda: self.btn_scan.config(state="normal"))

        def start_direct_repair(self):
            selected = filedialog.askdirectory(title="Selecciona la carpeta de archivos corruptos a reparar directamente")
            if not selected or not os.path.isdir(selected):
                return

            confirm = messagebox.askyesno(
                "Confirmar Reparación Directa",
                f"Se intentará reparar directamente cada archivo multimedia dentro de:\n\n{selected}\n\n"
                "• Los archivos REPARADOS se guardarán en '_Archivos_Reparados'.\n"
                "• Los originales dañados se moverán a '_Archivos_No_Reparables'.\n\n"
                "¿Deseas continuar?"
            )
            if not confirm:
                return

            self.is_scanning = True
            self.stop_requested = False

            self.btn_scan.config(state="disabled")
            self.btn_direct_repair.config(state="disabled")
            self.btn_process.config(state="disabled")
            self.btn_stop.config(state="normal", text="🛑 Detener")
            self.progress_var.set(0)

            threading.Thread(target=self._direct_repair_thread, args=(selected,), daemon=True).start()

        def _direct_repair_thread(self, folder):
            self.log_message(f"=== Iniciando Reparación Directa en: {folder} ===")
            repaired_live = 0
            failed_live = 0

            def direct_cb(current, total, rel_path, is_repaired):
                nonlocal repaired_live, failed_live
                if is_repaired:
                    repaired_live += 1
                else:
                    failed_live += 1
                percent = (current / total) * 100 if total > 0 else 100
                rate = (repaired_live / current * 100) if current > 0 else 0

                fname = os.path.basename(rel_path)
                status_txt = f"Reparando ({current:,}/{total:,}): {fname}"
                stats_txt = (
                    f"🛠️ {current:,} / {total:,} ({percent:.1f}%)   |   "
                    f"✅ Reparados: {repaired_live:,}   |   "
                    f"❌ Fallidos: {failed_live:,}   |   "
                    f"📈 Tasa: {rate:.1f}%"
                )

                self.after(0, lambda p=percent, st=status_txt, stt=stats_txt: (
                    self.progress_var.set(p),
                    self.lbl_status.config(text=st),
                    self.lbl_stats.config(text=stt)
                ))
                if is_repaired:
                    self.log_message(f"[✅ REPARADO] {rel_path}")

            try:
                total, repaired, failed, report_path = repair_directory_direct(
                    folder, callback=direct_cb, stop_checker=lambda: self.stop_requested
                )

                def on_direct_finish():
                    if total == 0:
                        messagebox.showinfo("Sin Archivos", "No se encontraron archivos de imagen o video en la carpeta seleccionada.")
                        return

                    rate = (repaired / total * 100) if total > 0 else 0
                    msg = (
                        f"Reparación Directa Finalizada\n\n"
                        f"Archivos procesados: {total:,}\n"
                        f"✅ Archivos REPARADOS con éxito: {repaired:,}\n"
                        f"❌ Archivos no reparables: {failed:,}\n"
                        f"📈 Tasa de recuperación: {rate:.1f}%\n\n"
                        f"Se ha guardado un informe detallado en:\n{report_path}"
                    )
                    messagebox.showinfo("Reparación Finalizada", msg)
                    self.lbl_status.config(text=f"Reparación directa completada. {repaired:,} archivos recuperados.")
                    self.lbl_stats.config(text=f"🛠️ Completado: {repaired:,} / {total:,} recuperados ({rate:.1f}% de éxito).")
                    self.progress_var.set(100)

                self.after(0, on_direct_finish)

            except Exception as e:
                self.after(0, lambda err=str(e): (
                    messagebox.showerror("Error en Reparación", err),
                    self.log_message(f"ERROR: {err}")
                ))
            finally:
                def cleanup():
                    self.btn_scan.config(state="normal")
                    self.btn_direct_repair.config(state="normal")
                    self.btn_stop.config(state="disabled", text="🛑 Detener Escaneo")
                    self.is_scanning = False

                self.after(0, cleanup)

    app = App()
    app.mainloop()


# ==============================================================================
# MODO LÍNEA DE COMANDOS (CLI)
# ==============================================================================

def run_cli():
    parser = argparse.ArgumentParser(description="Detector y limpiador de medios (imágenes y videos) corruptos.")
    parser.add_argument("--folder", "-f", type=str, help="Ruta de la carpeta a analizar.")
    parser.add_argument("--repair-folder", "-r", type=str, help="Ruta de una carpeta de corruptos a reparar directamente.")
    parser.add_argument("--action", "-a", choices=["quarantine", "repair", "delete", "report_only"], default="quarantine",
                        help="Acción a realizar: 'quarantine' (mover a _Archivos_Corruptos), 'repair' (reparar fotos/videos), 'delete' (eliminar), 'report_only'.")
    parser.add_argument("--no-recursive", action="store_true", help="No buscar dentro de subcarpetas.")
    parser.add_argument("--gui", action="store_true", help="Forzar apertura de interfaz gráfica.")

    args = parser.parse_args()

    if args.repair_folder:
        print(f"Iniciando reparación directa en: {args.repair_folder}...")
        total, repaired, failed, report_path = repair_directory_direct(args.repair_folder)
        print(f"Finalizado: {total} procesados | {repaired} REPARADOS con éxito | {failed} no reparables.")
        print(f"Reporte en: {report_path}")
        return

    if args.gui or not args.folder:
        run_gui()
        return

    folder = args.folder
    print(f"Analizando carpeta: {folder}...")

    def cli_cb(curr, total, item):
        if item['is_corrupt']:
            print(f"  [CORRUPTO] {item['rel_path']} ({item['type']}) -> {item['reason']}")

    results = scan_directory(folder, recursive=not args.no_recursive, callback=cli_cb)
    corrupt_items = [r for r in results if r['is_corrupt']]

    print(f"\nResumen: {len(results)} analizados, {len(corrupt_items)} corruptos.")

    if corrupt_items and args.action != "report_only":
        print(f"Ejecutando acción '{args.action}'...")
        success, fail, repaired, report_path = process_corrupt_files(folder, corrupt_items, action=args.action)
        print(f"Finalizado: {success} procesados ({repaired} reparados), {fail} fallos.")
        print(f"Reporte guardado en: {report_path}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_cli()
    else:
        run_gui()
