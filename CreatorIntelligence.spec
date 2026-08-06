from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("creator_intelligence")

a = Analysis(
    ["creator_intelligence/__main__.py"],
    pathex=["."],
    binaries=[],
    datas=[("config/modules.json", "config")],
    hiddenimports=hiddenimports,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CreatorIntelligence",
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="CreatorIntelligence",
)
