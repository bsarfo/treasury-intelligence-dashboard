@echo off
REM Run all smoke tests in sequence

call venv\Scripts\activate.bat
set PYTHONPATH=.

echo.
echo ============================================
echo  Test 1/5: FRED client (rates + macro data)
echo ============================================
python -m src.fred_client
if errorlevel 1 ( echo FAILED & pause & exit /b 1 )

echo.
echo ============================================
echo  Test 2/5: SEC EDGAR client (Carnival 10-K)
echo ============================================
python -m src.sec_client
if errorlevel 1 ( echo FAILED & pause & exit /b 1 )

echo.
echo ============================================
echo  Test 3/5: Treasury metrics (credit ratios)
echo ============================================
python -m src.treasury_metrics
if errorlevel 1 ( echo FAILED & pause & exit /b 1 )

echo.
echo ============================================
echo  Test 4/5: Liquidity forecast (13-week)
echo ============================================
python -m src.liquidity_forecast
if errorlevel 1 ( echo FAILED & pause & exit /b 1 )

echo.
echo ============================================
echo  Test 5/5: Risk engine (VaR, FX, maturity)
echo ============================================
python -m src.risk_engine
if errorlevel 1 ( echo FAILED & pause & exit /b 1 )

echo.
echo ============================================
echo  All 5 tests passed - ready for Phase 4!
echo ============================================
pause
