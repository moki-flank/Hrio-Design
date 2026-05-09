@echo off
setlocal enabledelayedexpansion

set "OUTPUT_FILE=project_export.txt"

echo Exporting project...

echo ======================================================================== > "%OUTPUT_FILE%"
echo Project Export >> "%OUTPUT_FILE%"
echo Export Time: %date% %time% >> "%OUTPUT_FILE%"
echo ======================================================================== >> "%OUTPUT_FILE%"
echo. >> "%OUTPUT_FILE%"
echo [Directory Structure] >> "%OUTPUT_FILE%"
echo. >> "%OUTPUT_FILE%"

tree /f /a >> "%OUTPUT_FILE%" 2>nul

echo. >> "%OUTPUT_FILE%"
echo ======================================================================== >> "%OUTPUT_FILE%"
echo [File Contents] >> "%OUTPUT_FILE%"
echo ======================================================================== >> "%OUTPUT_FILE%"

for /r %%f in (*.py *.json *.md *.yaml *.dart *.html *.ini *.js) do (
    echo. >> "%OUTPUT_FILE%"
    echo ------------------------------------------------------------------------ >> "%OUTPUT_FILE%"
    echo FILE: %%f >> "%OUTPUT_FILE%"
    echo ------------------------------------------------------------------------ >> "%OUTPUT_FILE%"
    echo. >> "%OUTPUT_FILE%"
    type "%%f" >> "%OUTPUT_FILE%" 2>nul
    echo. >> "%OUTPUT_FILE%"
)

echo Done! Output: %CD%\%OUTPUT_FILE%
pause