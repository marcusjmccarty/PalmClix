# Build PalmClix for Windows (run from the repository root or this folder).
#   powershell -ExecutionPolicy Bypass -File windows\build_windows.ps1
# Produces windows\dist\PalmClix\ (PalmClix.exe + palmclix_backend.exe) and PalmClix-Windows.zip.
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $Here
Set-Location $Root

$LibusbVersion = "1.0.27"
$Py = "python"

Write-Host "1/6 Python environment"
if (-not (Test-Path "$Root\.venv-win\Scripts\python.exe")) { & $Py -m venv "$Root\.venv-win" }
$Venv = "$Root\.venv-win\Scripts\python.exe"
& $Venv -m pip install --upgrade pip | Out-Null
& $Venv -m pip install -r requirements.txt "pyinstaller>=6,<7"
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

Write-Host "2/6 libusb $LibusbVersion"
$Dll = "$Here\libusb-1.0.dll"
if (-not (Test-Path $Dll)) {
  $Archive = "$env:TEMP\libusb-$LibusbVersion.7z"
  Invoke-WebRequest "https://github.com/libusb/libusb/releases/download/v$LibusbVersion/libusb-$LibusbVersion.7z" -OutFile $Archive
  $Out = "$env:TEMP\libusb-$LibusbVersion"
  & 7z x $Archive "-o$Out" -y | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Could not extract libusb (is 7-Zip installed?)" }
  $Found = Get-ChildItem $Out -Recurse -Filter "libusb-1.0.dll" |
    Where-Object { $_.FullName -match "MS64|x64|MinGW64" -and $_.FullName -match "dll" } |
    Select-Object -First 1
  if (-not $Found) { throw "64-bit libusb-1.0.dll not found in the libusb archive" }
  Write-Host "   using $($Found.FullName)"
  Copy-Item $Found.FullName $Dll
}

Write-Host "3/6 Icon"
& $Venv -c "from PIL import Image; Image.open(r'$Root\Artwork\PalmClix_icon_1024.png').save(r'$Here\PalmClix.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"

Write-Host "4/6 Tests"
& $Venv -m unittest discover -s tests
if ($LASTEXITCODE -ne 0) { throw "Unit tests failed" }

Write-Host "5/6 PyInstaller"
& $Venv -m PyInstaller --noconfirm --clean --distpath "$Here\dist" --workpath "$Here\build" "$Here\PalmClix.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host "6/6 Smoke test + zip"
$Helper = "$Here\dist\PalmClix\palmclix_backend.exe"
& $Helper --forensics "$Root\tests\fixtures\after_power_loss_catalog.bin" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Packaged backend failed its offline catalog test" }
if (Test-Path "$Root\reference_capture.pcap") {
  $Smoke = Join-Path $env:TEMP ("palmclix-smoke-" + [guid]::NewGuid())
  & $Helper --simulate "$Root\reference_capture.pcap" --format png --output $Smoke | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Packaged backend replay failed" }
}
Copy-Item "$Here\README-Windows.txt" "$Here\dist\PalmClix\README.txt" -Force
$Zip = "$Root\PalmClix-Windows.zip"
if (Test-Path $Zip) { Remove-Item $Zip }
Compress-Archive -Path "$Here\dist\PalmClix" -DestinationPath $Zip
Write-Host "Built $Zip"
