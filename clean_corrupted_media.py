#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Limpiador de Medios Corruptos (Imágenes y Videos)
Detecta y elimina o mueve archivos de imagen y video dañados/corruptos tras procesos de recuperación de datos.
"""

import os
import sys
import shutil
import argparse
import datetime
import threading
from pathlib import Path

# Intentar importar librerías externas opcionales pero recomendadas
HAS_PIL = False
try:
    from PIL import Image, ImageFile
    # Permitir cargar imágenes truncadas parcialmente para evaluar exactamente
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    HAS_PIL = True
except ImportError:
    pass

HAS_CV2 = False
try:
    os.environ["OPENCV_FFMPEG_LOG_LEVEL"] = "-8"
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
    if not completed.wait(timeout=timeout):
        return True, "Tiempo límite excedido (video extremadamente dañado que congela el códec)"

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


def process_corrupt_files(folder_path: str, corrupt_items: list, action: str = "quarantine"):
    """
    Aplica la acción seleccionada ('quarantine' o 'delete') a los archivos corruptos.
    Genera un informe con los detalles.
    """
    folder = Path(folder_path)
    report_lines = [
        "==================================================",
        "INFORME DE LIMPIEZA DE MEDIOS CORRUPTOS",
        f"Fecha y Hora: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Carpeta Analizada: {folder_path}",
        f"Acción Realizada: {'Mover a Cuarentena' if action == 'quarantine' else 'Eliminar Definitivamente'}",
        "==================================================\n"
    ]

    quarantine_dir = folder / "_Archivos_Corruptos"
    if action == "quarantine" and corrupt_items:
        quarantine_dir.mkdir(exist_ok=True)

    success_count = 0
    fail_count = 0

    for item in corrupt_items:
        src = Path(item['path'])
        if not src.exists():
            continue

        try:
            if action == "quarantine":
                dst = quarantine_dir / item['rel_path']
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                report_lines.append(f"[MOVIDO] {item['rel_path']} -> _Archivos_Corruptos | Razón: {item['reason']}")
            elif action == "delete":
                os.remove(str(src))
                report_lines.append(f"[ELIMINADO] {item['rel_path']} | Razón: {item['reason']}")
            success_count += 1
        except Exception as e:
            fail_count += 1
            report_lines.append(f"[ERROR] No se pudo procesar {item['rel_path']}: {str(e)}")

    report_lines.append(f"\nResumen: {success_count} procesados con éxito, {fail_count} errores.")
    
    report_path = folder / "reporte_limpieza_corruptos.txt"
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))
    except Exception as e:
        print(f"Error escribiendo el reporte: {e}")

    return success_count, fail_count, str(report_path)


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

            self.btn_scan = ttk.Button(btn_frame, text="🔍 Buscar Archivos Corruptos", command=self.start_scan)
            self.btn_scan.pack(side="left", padx=4, expand=True, fill="x")

            self.btn_stop = ttk.Button(btn_frame, text="🛑 Detener Escaneo", command=self.stop_scan, state="disabled")
            self.btn_stop.pack(side="left", padx=4, expand=True, fill="x")

            self.btn_process = ttk.Button(btn_frame, text="⚠️ Procesar / Limpiar Corruptos", command=self.start_process, state="disabled")
            self.btn_process.pack(side="left", padx=4, expand=True, fill="x")

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
            action_str = "MOVER a '_Archivos_Corruptos'" if action == "quarantine" else "ELIMINAR PERMANENTEMENTE"
            
            confirm = messagebox.askyesno(
                "Confirmar Acción",
                f"Vas a realizar la siguiente acción sobre {len(self.corrupt_items)} archivos corruptos:\n\n"
                f"Acción: {action_str}\n\n"
                "¿Deseas continuar?"
            )
            
            if not confirm:
                return

            folder = self.entry_folder.get().strip()
            success, fail, report_path = process_corrupt_files(folder, self.corrupt_items, action=action)

            messagebox.showinfo(
                "Proceso Finalizado",
                f"Se han procesado los archivos corruptos.\n\n"
                f"Éxitos: {success}\n"
                f"Errores: {fail}\n\n"
                f"Se ha guardado un informe detallado en:\n{report_path}"
            )

            # Limpiar lista tras procesar
            self.tree_corrupt.delete(*self.tree_corrupt.get_children())
            self.corrupt_items.clear()
            self.btn_process.config(state="disabled")
            self.tab_corrupt_ref.tab(0, text=" Archivos Corruptos (0) ")
            self.lbl_status.config(text="Archivos procesados correctamente.")

    app = App()
    app.mainloop()


# ==============================================================================
# MODO LÍNEA DE COMANDOS (CLI)
# ==============================================================================

def run_cli():
    parser = argparse.ArgumentParser(description="Detector y limpiador de medios (imágenes y videos) corruptos.")
    parser.add_argument("--folder", "-f", type=str, help="Ruta de la carpeta a analizar.")
    parser.add_argument("--action", "-a", choices=["quarantine", "delete", "report_only"], default="quarantine",
                        help="Acción a realizar con los archivos corruptos: 'quarantine' (mover a _Archivos_Corruptos), 'delete' (eliminar), 'report_only' (solo informe).")
    parser.add_argument("--no-recursive", action="store_true", help="No buscar dentro de subcarpetas.")
    parser.add_argument("--gui", action="store_true", help="Forzar apertura de interfaz gráfica.")

    args = parser.parse_args()

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
        success, fail, report_path = process_corrupt_files(folder, corrupt_items, action=args.action)
        print(f"Finalizado: {success} procesados, {fail} fallos.")
        print(f"Reporte guardado en: {report_path}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_cli()
    else:
        run_gui()
