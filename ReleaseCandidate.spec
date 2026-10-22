"""Production-default local RC, no QA entry or seeded profiles; no installer is executed."""
import json
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

root = Path(SPECPATH)
sys.path.insert(0, str(root / 'scripts'))
from ssl_resources import ssl_datas, public_ssl_resources
from release_compliance import runtime_module, release_native_binaries

preparation = Path(os.environ['CDA_RELEASE_PREP']).resolve()
if not preparation.is_relative_to(root / 'release-prep'):
    raise RuntimeError('Release output must be isolated in release-prep')
ssl_manifest = preparation / 'build-inputs/ssl-runtime-resources.json'
if json.loads(ssl_manifest.read_text(encoding='utf-8')) != public_ssl_resources():
    raise RuntimeError('SSL build inputs changed')
data, binaries, hidden = [], [], []
for package in ('webview','pythonnet','clr_loader'):
    d,b,h = collect_all(package, filter_submodules=runtime_module)
    data += d
    binaries += b
    hidden += h
analysis = Analysis(
    [str(root / 'scripts/release_entry.py')],
    pathex=[str(root / 'src'),str(root / 'scripts'),str(root / '.ui-deps'),os.environ['CANVAS_DEPENDENCY_DIR']],
    datas=data+ssl_datas()+collect_data_files('certifi')+collect_data_files('tzdata')+[
        (str(root/'frontend'),'frontend'),(str(ssl_manifest),'.'),
        (str(preparation/'build-inputs/frontend-sha256.json'),'.'),
        (str(preparation/'build-inputs/release-info.json'),'.')],
    binaries=binaries,
    hiddenimports=hidden+collect_submodules('winrt')+['webview.platforms.edgechromium','webview.platforms.winforms',
        'clr','pythonnet','clr_loader','cffi','_cffi_backend','pythoncom','pywintypes','win32api','win32security','win32com.client.dynamic'],
    # xref: setuptools is reached through CFFI's compiler helper, not CLR's ABI mode.
    # Actual frozen CFFI/NetFx initialization is checked without importing a renderer.
    excludes=['PyInstaller','webview.__pyinstaller','setuptools','_distutils_hack',
        'cffi._shimmed_dist_utils','cffi.ffiplatform','cffi.verifier','cffi.recompiler',
        'pytest','ruff','pip_audit','PyQt5','PyQt6','PySide2','PySide6','cefpython3',
        'ui_review_entry','canvas_agent.web_qa','canvas_agent.backend_check','canvas_agent.credential_check',
        'canvas_agent.gui','canvas_agent.copilot_gui','canvas_agent.desktop','canvas_agent.desktop_settings',
        'canvas_agent.desktop_tasks','canvas_agent.widgets','tkinter'],
    noarchive=False,
)
analysis.binaries, removed_system_components, substitutions = release_native_binaries(
    analysis.binaries, root, preparation/'build-inputs/native-assets')
(preparation/'evidence/system-components-not-redistributed.json').write_text(
    json.dumps(removed_system_components, indent=2), encoding='utf-8')
(preparation/'evidence/native-substitutions.json').write_text(
    json.dumps(substitutions, indent=2), encoding='utf-8')
pyz=PYZ(analysis.pure)
exe=EXE(pyz,analysis.scripts,[],exclude_binaries=True,name='CanvasDeadlineAgent',console=False,upx=False,
        version=str(preparation/'build-inputs/version-info.txt'),disable_windowed_traceback=True)
collection=COLLECT(exe,analysis.binaries,analysis.datas,name='CanvasDeadlineAgent',upx=False)
