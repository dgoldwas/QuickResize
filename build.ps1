$ErrorActionPreference = "Stop"
py -m pip install -r requirements.txt pyinstaller
pyinstaller --noconsole --onefile --clean --icon assets\QuickResize.ico --add-data "assets;assets" --collect-all rawpy --name QuickResize quickresize.py
Write-Host "Built dist\QuickResize.exe"
