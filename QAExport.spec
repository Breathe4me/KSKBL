"""Independent local QA onedir. Does not build or replace any installer."""
import os
import json
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

root = Path(SPECPATH)
sys.path.insert(0, str(root / 'scripts'))
from ssl_resources import ssl_datas, ssl_resources
frontend_manifest = Path(os.environ['CDA_FRONTEND_MANIFEST']).resolve()
if not frontend_manifest.is_file() or not frontend_manifest.is_relative_to(root / 'qa-export'):
    raise RuntimeError('Supply a fresh QA export frontend integrity manifest')
ssl_manifest = frontend_manifest.with_name('ssl-runtime-resources.json')
if json.loads(ssl_manifest.read_text(encoding='utf-8')) != ssl_resources():
    raise RuntimeError('SSL runtime policy resource differs from prepared build inputs')
all_data, all_bins, all_hidden = [], [], []
for name in ('webview', 'pythonnet', 'clr_loader'):
    datas, binaries, hidden = collect_all(name)
    all_data += datas
    all_bins += binaries
    all_hidden += hidden

analysis = Analysis(
    [str(root / ('scripts/integration_entry.py' if os.environ.get('CDA_FULL_APP_ENTRY') == '1' else 'scripts/ui_review_entry.py'))],
    pathex=[str(root / 'src'), str(root / '.ui-deps'), os.environ['CANVAS_DEPENDENCY_DIR']],
    datas=all_data + ssl_datas() + [(str(ssl_manifest), '.'), (str(root / 'frontend'), 'frontend'), (str(frontend_manifest), '.')] + collect_data_files('tzdata') + collect_data_files('certifi'),
    binaries=all_bins,
    hiddenimports=all_hidden + collect_submodules('winrt') + [
        'webview.platforms.edgechromium', 'webview.platforms.winforms',
        'clr', 'pythonnet', 'clr_loader', 'cffi', '_cffi_backend', 'bottle', 'proxy_tools',
        'pythoncom', 'pywintypes', 'win32api', 'win32security', 'win32com.client.dynamic'],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'cefpython3', 'pytest', 'pip_audit', 'ruff'],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name='CanvasDeadlineAgent-UI-QA',
          console=True, upx=False, disable_windowed_traceback=True)
collection = COLLECT(exe, analysis.binaries, analysis.datas, name='CanvasDeadlineAgent-UI-QA', upx=False)
