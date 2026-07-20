# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

block_cipher = None

# Collect hidden imports and data for complex packages
datas = []
datas += collect_data_files('flask')
datas += collect_data_files('socketio')
datas += collect_data_files('engineio')
datas += collect_data_files('chromadb')
datas += collect_data_files('mcp')
datas += collect_data_files('onnxruntime')
datas += collect_data_files('tokenizers')
datas += collect_data_files('tqdm')

binaries = []
binaries += collect_dynamic_libs('onnxruntime')
binaries += collect_dynamic_libs('tokenizers')

hiddenimports = []
hiddenimports += collect_submodules('engineio')
hiddenimports += collect_submodules('socketio')
hiddenimports += collect_submodules('openai')
hiddenimports += collect_submodules('chromadb')
hiddenimports += collect_submodules('mcp')
hiddenimports += collect_submodules('onnxruntime')
hiddenimports += collect_submodules('tokenizers')
hiddenimports += collect_submodules('tqdm')
hiddenimports += ['backend.mcp.server']

# Bundle the frontend folder
datas += [('frontend', 'frontend')]

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    name='My MCM',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='frontend/img/icon.ico'
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='My MCM',
)
