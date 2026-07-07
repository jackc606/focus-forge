# PyInstaller spec for Focus Forge — one-folder Windows build (fast launch).
# Build with:  python -m PyInstaller build.spec --clean --noconfirm
# Output:      dist/FocusForge/FocusForge.exe        (windowed GUI)
#              dist/FocusForge/focusforge-mcp.exe     (console MCP server)
# The Inno Setup installer (installer.iss) packages that folder.

from PyInstaller.utils.hooks import collect_submodules

# The MCP server pulls these in dynamically; make sure they're bundled.
_MCP_HIDDEN = (
    collect_submodules("mcp")
    + collect_submodules("pydantic")
    + collect_submodules("pydantic_core")
    + ["focusforge_mcp", "focusforge_mcp.server", "core.bridge_discovery"]
)

_COMMON_EXCLUDES = [
    'tkinter',
    'matplotlib',
    'numpy',
    'PIL',
    'notebook',
    'IPython',
    'pytest',
]
_GUI_EXCLUDES = _COMMON_EXCLUDES + [
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets',
    'PySide6.Qt3DCore',
    'PySide6.Qt3DRender',
    'PySide6.QtCharts',
    'PySide6.QtDataVisualization',
    'PySide6.QtMultimedia',
    'PySide6.QtMultimediaWidgets',
    'PySide6.QtPositioning',
    'PySide6.QtSensors',
]
# The MCP server is headless — keep the whole Qt stack out of it.
_MCP_EXCLUDES = _COMMON_EXCLUDES + ['PySide6', 'shiboken6']

# ---- GUI executable -------------------------------------------------------
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # icon.ico rides along for the runtime window icon (main._icon_path finds
    # it under _MEIPASS/assets); the exe-embedded icon below covers Explorer.
    datas=[('assets/icon.ico', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_GUI_EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FocusForge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
)

# ---- MCP server executable (console, for stdio) ---------------------------
a_mcp = Analysis(
    ['mcp_server_main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=_MCP_HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_MCP_EXCLUDES,
    noarchive=False,
)
pyz_mcp = PYZ(a_mcp.pure)
exe_mcp = EXE(
    pyz_mcp,
    a_mcp.scripts,
    [],
    exclude_binaries=True,
    name='focusforge-mcp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# ---- collect both into one folder ----------------------------------------
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    exe_mcp,
    a_mcp.binaries,
    a_mcp.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FocusForge',
)
