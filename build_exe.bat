@echo off
echo ========================================================
echo   Compilando Limpiador de Medios Corruptos a EXE
echo ========================================================
echo.

echo 1. Instalando dependencias necesarias...
python -m pip install -r requirements.txt

echo.
echo 2. Generando ejecutable portable...
pyinstaller --noconfirm --onedir --windowed --name "LimpiadorMediosCorruptos" --clean clean_corrupted_media.py

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================================
    echo   COMPILACION EXITOSA!
    echo   El ejecutable esta en:
    echo   dist\LimpiadorMediosCorruptos\LimpiadorMediosCorruptos.exe
    echo ========================================================
) else (
    echo.
    echo Ocurrio un error durante la compilacion.
)

pause
