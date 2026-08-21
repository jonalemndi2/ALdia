@echo off
chcp 65001 >nul
title ALdia - Instalacion
color 0B
echo ============================================
echo     ALDIA - Instalacion del sistema
echo ============================================
echo.
echo  Este proceso prepara el sistema en esta PC (servidor).
echo  Solo debe ejecutarse una vez.
echo.

cd /d "%~dp0"

REM Verificar que Python este instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python no esta instalado o no esta en el PATH.
    echo  Descarguelo desde https://www.python.org/downloads/
    echo  Durante la instalacion marque la opcion "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

echo  [1/4] Creando entorno virtual...
if not exist ".venv" (
    python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
    echo  [ERROR] No se pudo crear el entorno virtual en:
    echo  %CD%\.venv
    echo  Verifique que tiene permisos de escritura en esta carpeta.
    pause
    exit /b 1
)

echo  [2/4] Actualizando pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul

echo  [3/4] Instalando dependencias...
".venv\Scripts\python.exe" -m pip install -r "backend\requirements.txt"
if errorlevel 1 (
    echo  [ERROR] Fallo la instalacion de dependencias.
    echo  Revise su conexion a internet y vuelva a intentarlo.
    pause
    exit /b 1
)

REM Comprobar que el sistema realmente arranca, en vez de dar por buena la
REM instalacion solo porque pip no devolvio error.
echo  [4/4] Verificando la instalacion...
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, sqlalchemy, pydantic, bcrypt, jwt, httpx" 2>nul
if errorlevel 1 (
    echo  [ERROR] Las dependencias se instalaron pero no se pueden importar.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  Instalacion completada y verificada.
echo  Ahora puede iniciar el sistema con:  iniciar_web.bat
echo ============================================
echo.
pause
