$ErrorActionPreference = "Stop"
py -m pip install -r requirements.txt pyinstaller
pyinstaller --noconsole --onefile --clean --collect-all rawpy --collect-all pymupdf --name QuickResize quickresize.py
Write-Host "Built dist\QuickResize.exe"
