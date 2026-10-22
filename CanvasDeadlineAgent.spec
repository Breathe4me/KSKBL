import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

root = Path(SPECPATH)
sys.path.insert(0, str(root / 'scripts'))
from ssl_resources import ssl_datas
build_info = os.environ.get('CANVAS_BUILD_INFO')
version_info = os.environ.get('CANVAS_VERSION_INFO')
if not build_info or not version_info:
    raise RuntimeError('Use scripts/build.ps1 to create a uniquely identified development candidate')
if not all(Path(p).resolve().is_relative_to(root / 'build-candidates') for p in (build_info, version_info)):
    raise RuntimeError('Build metadata must be inside this project candidate directory')

webview_datas, webview_binaries, webview_hidden = collect_all('webview')
analysis = Analysis(
    [str(root / 'scripts' / 'entry.py')],
    pathex=[str(root / 'src'), str(root / '.ui-deps'), os.environ.get('CANVAS_DEPENDENCY_DIR', str(root / '.deps'))],
    binaries=webview_binaries,
    datas=webview_datas + ssl_datas() + [(str(root / 'frontend'), 'frontend'), (build_info, 'notices')] + collect_data_files('tzdata') + collect_data_files('certifi') + [(str(root / 'docs' / 'THIRD_PARTY_NOTICES.md'), 'notices')],
    hiddenimports=['tkinter', 'tkinter.ttk', 'tkinter.messagebox', 'tkinter.filedialog',
                   'pythoncom', 'pywintypes', 'win32api', 'win32security',
                   'win32com.client.dynamic', 'webview.platforms.edgechromium', 'webview.platforms.winforms', 'clr_loader', 'pythonnet', '_cffi_backend'] + webview_hidden + collect_submodules('winrt'),
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=['pytest', 'pip_audit', 'ruff', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'cefpython3'],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name='CanvasDeadlineAgent',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          disable_windowed_traceback=True, version=version_info)
collection = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name='CanvasDeadlineAgent')
