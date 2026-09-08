@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM  COG Mosaic Builder - AOI to mosaic to raster templates
REM  Double-click to run. No editing required.
REM ============================================================

set "REPO_ROOT=%~dp0.."
set "CONFIG_FILE=%REPO_ROOT%\config.json"
set "DEFAULT_PYTHON=C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"

echo ============================================================
echo  COG Mosaic Builder
echo ============================================================
echo.

REM ********* Step 1: Check config.json exists **************
echo [1/6] Checking config.json...
if not exist "%CONFIG_FILE%" (
    echo.
    echo ERROR: config.json not found.
    echo Expected location: %CONFIG_FILE%
    echo.
    echo Please make sure config.json is in the root of the project folder.
    echo Open config.json and set your AOI, dates, and output folder.
    echo.
    pause
    exit /b 1
)
echo       OK - config.json found.
echo.

REM ********* Step 2: Locate ArcGIS Pro Python **************
echo [2/6] Locating ArcGIS Pro Python...
set "pPath="

REM Try the default install path first
if exist "%DEFAULT_PYTHON%" (
    set "pPath=%DEFAULT_PYTHON%"
    echo       Found at default location.
    goto :python_found
)

REM Fallback: search registry for ArcGIS Pro install directory
echo       Not at default path. Searching registry...
for /f "tokens=2*" %%A in ('reg query "HKLM\SOFTWARE\ESRI\ArcGISPro" /v "InstallDir" 2^>nul') do (
    set "ARCGIS_DIR=%%B"
)
if defined ARCGIS_DIR (
    set "pPath=!ARCGIS_DIR!bin\Python\envs\arcgispro-py3\python.exe"
    if exist "!pPath!" (
        echo       Found via registry: !pPath!
        goto :python_found
    )
)

REM Fallback: search registry under Wow6432Node
for /f "tokens=2*" %%A in ('reg query "HKLM\SOFTWARE\Wow6432Node\ESRI\ArcGISPro" /v "InstallDir" 2^>nul') do (
    set "ARCGIS_DIR=%%B"
)
if defined ARCGIS_DIR (
    set "pPath=!ARCGIS_DIR!bin\Python\envs\arcgispro-py3\python.exe"
    if exist "!pPath!" (
        echo       Found via registry (Wow6432Node): !pPath!
        goto :python_found
    )
)

REM Fallback: try common alternate drive letters
for %%D in (D E F) do (
    set "ALT=%%D:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
    if exist "!ALT!" (
        set "pPath=!ALT!"
        echo       Found on drive %%D:.
        goto :python_found
    )
)

REM Nothing found
echo.
echo ERROR: ArcGIS Pro Python could not be found automatically.
echo.
echo Checked:
echo   - C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe
echo   - Windows registry (HKLM\SOFTWARE\ESRI\ArcGISPro)
echo   - Common alternate drives (D, E, F)
echo.
echo To fix: open this batch file in Notepad and set the DEFAULT_PYTHON
echo variable at the top to the correct path of your python.exe.
echo.
echo ArcGIS Pro must be installed to run this tool.
echo.
pause
exit /b 1

:python_found
echo       Using: %pPath%
echo.

REM ********* Step 3: Create required directories **************
echo [3/6] Creating required folders...
if not exist "C:\mrfcache\cachingmrf" (
    mkdir "C:\mrfcache\cachingmrf"
    echo       Created: C:\mrfcache\cachingmrf
) else (
    echo       OK - MRF cache folder exists.
)
echo.

REM ********* Step 4: Install required Python packages **************
echo [4/6] Checking required Python packages...
"%pPath%" -c "import pystac_client" >nul 2>&1
if errorlevel 1 (
    echo       pystac-client not found. Installing...
    "%pPath%" -m pip install pystac-client
    if errorlevel 1 (
        echo.
        echo ERROR: Failed to install pystac-client.
        echo.
        echo This usually means no internet access or a proxy is blocking pip.
        echo Try running this batch file with administrator rights, or install
        echo manually by running:
        echo   "%pPath%" -m pip install pystac-client
        echo.
        pause
        exit /b 1
    )
    echo       pystac-client installed successfully.
) else (
    echo       OK - pystac-client already installed.
)
echo.

REM ********* Step 5: Pre-flight checks (license, AOI, templates, overwrite warning) **************
echo [5/6] Running pre-flight checks...
echo.
"%pPath%" "%REPO_ROOT%\scripts\preflight_check.py"
set PREFLIGHT_EXIT=%errorlevel%

if %PREFLIGHT_EXIT%==2 (
    REM User declined the overwrite prompt — exit cleanly, no error
    exit /b 0
)
if %PREFLIGHT_EXIT%==1 (
    echo.
    echo ============================================================
    echo  Pre-flight checks failed. Fix the issues above and re-run.
    echo ============================================================
    echo.
    pause
    exit /b 1
)
echo.

REM ********* Step 6: Run the workflow **************
echo [6/6] Running mosaic workflow...
echo       (This may take several minutes depending on the number of AOI features)
echo.
"%pPath%" "%REPO_ROOT%\scripts\run_workflow.py"

if errorlevel 1 (
    echo.
    echo ============================================================
    echo  ERROR: Workflow failed. See the output above for details.
    echo ============================================================
    echo.
    echo Common causes:
    echo   - No internet access to reach the STAC API
    echo   - AOI has no scenes in the given date/cloud range
    echo   - Disk full on the output drive
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Done! Results saved to the output_folder in config.json.
echo ============================================================
echo.
pause
