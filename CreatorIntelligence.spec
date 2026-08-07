from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
for package in (
    "creator_intelligence",
    "google.oauth2",
    "google.auth.transport",
    "google_auth_oauthlib",
    "googleapiclient",
    "keyring.backends",
):
    hiddenimports.extend(collect_submodules(package))
hiddenimports = [
    module for module in hiddenimports
    if not module.startswith("creator_intelligence.tests")
]

a = Analysis(
    ["creator_intelligence/__main__.py"],
    pathex=["."],
    binaries=[],
    datas=[("config/modules.json", "config")],
    hiddenimports=hiddenimports,
    excludes=["creator_intelligence.tests", "pytest"],
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
