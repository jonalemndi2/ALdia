@echo off
chcp 65001 >nul
title ALdia - Servidor
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

REM Solo esta PC por defecto: abrirlo a la red local es una decision, no el
REM estado de fabrica (ver backend\main.py). Para las otras cajas:
REM     set ALDIA_HOST=0.0.0.0  antes de ejecutar este archivo.
if not defined ALDIA_HOST set "ALDIA_HOST=127.0.0.1"
if not defined ALDIA_PORT set "ALDIA_PORT=8000"

echo  En esta PC (servidor):   http://localhost:%ALDIA_PORT%
if "%ALDIA_HOST%"=="0.0.0.0" (
    for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
        for /f "tokens=* delims= " %%b in ("%%a") do echo  Desde otras PCs:         http://%%b:%ALDIA_PORT%
    )
) else (
    echo  ^(solo esta PC; para las otras cajas: set ALDIA_HOST=0.0.0.0^)
)
echo.
if exist "%~dp0backend\.aldia_clave_inicial" (
    set /p CLAVE_INICIAL=<"%~dp0backend\.aldia_clave_inicial"
    call echo  Usuario inicial:  admin    Contrasena:  %%CLAVE_INICIAL%%
    echo  ^(El sistema le exige cambiarla antes de dejarlo operar^)
) else if not exist "%~dp0backend\aldia.db" (
    echo  Primer arranque: la contrasena inicial de admin se muestra abajo
    echo  y queda en backend\.aldia_clave_inicial hasta que la cambie.
)
echo.
echo  Abriendo navegador...
start "" http://localhost:%ALDIA_PORT%

echo  Servidor activo. Cierre esta ventana para detener el sistema.
echo ============================================
"%PYTHON%" main.py
pause
