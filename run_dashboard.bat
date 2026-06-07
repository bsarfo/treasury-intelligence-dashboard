@echo off
REM Launch the Treasury Intelligence Dashboard

call venv\Scripts\activate.bat
set PYTHONPATH=.

echo.
echo Starting Treasury Intelligence Dashboard...
echo Browser will open at http://localhost:8501
echo Press Ctrl+C in this window to stop the server.
echo.

streamlit run app.py
