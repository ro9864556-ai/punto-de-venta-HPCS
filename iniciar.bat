@echo off
chcp 65001 > nul
title Punto de Venta - Celulares
cd /d "%~dp0"
if not exist .venv (
  echo Instalando por primera vez, espera un momento...
  python -m venv .venv || (echo No se encontro Python. Instalalo desde https://www.python.org y marca "Add Python to PATH". & pause & exit /b 1)
  .venv\Scripts\python -m pip install --upgrade pip > nul
  .venv\Scripts\python -m pip install -r requirements.txt
)
.venv\Scripts\python app.py
pause
