# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path
import streamlit

streamlit_dir = Path(streamlit.__file__).parent
site_packages = streamlit_dir.parent

block_cipher = None

# Collect .dist-info metadata folders so importlib.metadata works at runtime
dist_info_packages = [
    'streamlit', 'altair', 'pandas', 'numpy', 'pyarrow', 'pillow',
    'click', 'tornado', 'pydeck', 'narwhals', 'blinker', 'cachetools',
    'gitpython', 'protobuf', 'tenacity', 'toml', 'packaging',
    'requests', 'certifi', 'charset_normalizer', 'idna', 'urllib3',
    'jinja2', 'MarkupSafe', 'attrs', 'jsonschema', 'referencing',
    'rpds_py', 'python_dateutil', 'six', 'typing_extensions', 'smmap',
    'gitdb', 'colorama', 'watchdog', 'setuptools', 'pywin32_ctypes',
]

metadata_datas = []
for folder in site_packages.iterdir():
    if folder.is_dir() and folder.suffix == '.dist-info':
        metadata_datas.append((str(folder), folder.name))

a = Analysis(
    ['Luminite_Setlist_Maker.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # Streamlit static assets
        (str(streamlit_dir / 'static'), 'streamlit/static'),
        (str(streamlit_dir / 'runtime'), 'streamlit/runtime'),
        # App files
        ('streamlit_app.py', '.'),
        ('analyze_backup.py', '.'),
        ('luminite', 'luminite'),
        # All .dist-info metadata (needed by importlib.metadata at runtime)
        *metadata_datas,
    ],
    hiddenimports=[
        'streamlit',
        'streamlit.web',
        'streamlit.web.cli',
        'streamlit.runtime.scriptrunner.magic_funcs',
        'streamlit.runtime.caching',
        'streamlit.runtime.caching.storage',
        'streamlit.runtime.caching.storage.local_message_cache',
        'streamlit.runtime.caching.storage.dummy_cache_storage',
        'streamlit.runtime.legacy_caching',
        'streamlit.runtime.legacy_caching.caching',
        'pyarrow',
        'altair',
        'pydeck',
        'pandas',
        'numpy',
        'PIL',
        'click',
        'tornado',
        'importlib.metadata',
        'importlib.resources',
        'pkg_resources.extern',
        'luminite.backup',
        'luminite.compiler',
        'luminite.library',
        'luminite.models',
        'analyze_backup',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LuminiteSetlistMaker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LuminiteSetlistMaker',
)
