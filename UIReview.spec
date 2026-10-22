import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)
wv_datas, wv_bins, wv_hidden = collect_all('webview')
analysis = Analysis([str(root / 'scripts/ui_review_entry.py')],
    pathex=[str(root/'src'), str(root/'.ui-deps'), os.environ.get('CANVAS_DEPENDENCY_DIR', str(root/'.deps'))],
    datas=wv_datas+[(str(root/'frontend'),'frontend')], binaries=wv_bins,
    hiddenimports=wv_hidden+['webview.platforms.edgechromium','webview.platforms.winforms','clr_loader','pythonnet','cffi','_cffi_backend','bottle','proxy_tools','pythoncom','pywintypes','win32security','win32com.client.dynamic'],
    excludes=['PyQt5','PyQt6','PySide2','PySide6','cefpython3','pytest','pip_audit','ruff'], noarchive=False)
pyz=PYZ(analysis.pure)
exe=EXE(pyz,analysis.scripts,[],exclude_binaries=True,name='CanvasDeadlineAgent-UIReview',console=False,upx=False,disable_windowed_traceback=True)
collection=COLLECT(exe,analysis.binaries,analysis.datas,name='CanvasDeadlineAgent-UIReview',upx=False)
