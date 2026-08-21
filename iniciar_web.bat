@echo off
chcp 65001 >nul
title ALdia - Servidor (Red Local)
color 0A
echo ============================================
echo     ALDIA - Servidor de Gestion
echo ============================================
echo.

cd /d "%~dp0backend"

REM Usar el entorno virtual si existe; si no, usar Python del sistema.
REM IMPORTANTE: la ruta va SIEMPRE entre comillas. Si la carpeta del proyecto
REM tiene espacios (ej. "G:\Programas IA\ALdia"), sin comillas Windows
REM intenta ejecutar "G:\Programas" y falla con errorlevel 9009, lo que antes
REM se reportaba como "faltan dependencias" aunque estuvieran todas instaladas.
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON=%~dp0.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

REM Verificar que Python se pueda ejecutar
"%PYTHON%" --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] No se puede ejecutar Python.
    echo.
    echo  Ruta probada:  %PYTHON%
    echo.
    if exist "%~dp0.venv\Scripts\python.exe" (
        echo  El entorno virtual existe pero no responde. Puede estar danado:
        echo  borre la carpeta .venv y vuelva a ejecutar  instalar.bat
    ) else (
        echo  No hay entorno virtual. Ejecute primero  instalar.bat
        echo  Si nunca instalo Python: https://www.python.org/downloads/
        echo  ^(marque "Add Python to PATH" durante la instalacion^)
    )
    echo.
    pause
    exit /b 1
)

REM Verificar las dependencias e informar EXACTAMENTE cual falta
"%PYTHON%" -c "import fastapi, uvicorn, sqlalchemy, pydantic, bcrypt, jwt, httpx" 2>nul
if errorlevel 1 (
    echo  [!] Faltan dependencias del sistema. Detalle:
    echo.
    "%PYTHON%" -c "import importlib,sys; [print('     falta:', m) for m in ['fastapi','uvicorn','sqlalchemy','pydantic','bcrypt','jwt','httpx'] if not importlib.util.find_spec(m)]"
    echo.
    echo  Ejecute  instalar.bat  para instalarlas.
    echo.
    pause
    exit /b 1
)

REM Mostrar la direccion IP local para conexion desde otras PCs
echo  El sistema estara disponible en esta PC y en la red local.
echo.
echo  En esta PC (servidor):   http://localhost:8000
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    for /f "tokens=* delims= " %%b in ("%%a") do echo  Desde otras PCs:         http://%%b:8000
)
echo.
echo  Usuario inicial:  admin    Contrasena:  admin123
echo  (Cambie la contrasena del administrador tras el primer ingreso)
echo.
echo  Abriendo navegador...
start "" http://localhost:8000

echo  Servidor activo. Cierre esta ventana para detener el sistema.
echo ============================================
set ALDIA_HOST=0.0.0.0
set ALDIA_PORT=8000
"%PYTHON%" main.py
pause
