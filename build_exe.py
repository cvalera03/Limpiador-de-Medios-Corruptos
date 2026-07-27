#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script auxiliar para compilar LimpiadorMediosCorruptos.exe usando Python.
"""
import subprocess
import sys
import os

def build():
    print("========================================================")
    print("  Compilando Limpiador de Medios Corruptos a EXE")
    print("========================================================\n")

    print("1. Instalando / Verificando dependencias...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])

    print("\n2. Generando ejecutable portable (LimpiadorMediosCorruptos.exe)...")
    cmd = [
        "pyinstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name", "LimpiadorMediosCorruptos",
        "--clean",
        "clean_corrupted_media.py"
    ]
    res = subprocess.run(cmd)

    if res.returncode == 0:
        print("\n========================================================")
        print("  ¡COMPILACIÓN EXITOSA!")
        print("  El ejecutable se encuentra en:")
        print(r"  dist\LimpiadorMediosCorruptos\LimpiadorMediosCorruptos.exe")
        print("========================================================\n")
    else:
        print("\n[ERROR] Ocurrió un error durante la compilación con PyInstaller.")

if __name__ == "__main__":
    build()
    input("Presiona Enter para salir...")
