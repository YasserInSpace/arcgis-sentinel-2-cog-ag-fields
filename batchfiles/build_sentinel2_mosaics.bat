@echo off
REM ********* Set Variable Values **************
set pPath="C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
set mdcsPath=%~dp0..

REM ********* Check ArcGIS Python exists **************
if not exist %pPath% (
    echo ERROR: ArcGIS Pro Python not found at %pPath%
    echo Please update pPath in this batch file.
    pause
    exit /b 1
)

REM ********* Create required directories **************
if not exist "C:\mrfcache\cachingmrf" mkdir "C:\mrfcache\cachingmrf"

REM ********* Install required Python packages **************
echo Checking required Python packages...
%pPath% -c "import pystac_client" 2>nul
if errorlevel 1 (
    echo Installing pystac-client...
    %pPath% -m pip install pystac-client
)

REM ********* Run workflow from shapefile using config.json **************
echo Running MDCS workflow...
echo Edit config.json to change AOI shapefile, dates, and cloud cover.
echo.
%pPath% "%mdcsPath%\scripts\run_from_shapefile.py"

if errorlevel 1 (
    echo.
    echo ERROR: Workflow failed. See output above for details.
    pause
    exit /b 1
)

echo.
echo Done! Check config.json output_folder for results.
pause
