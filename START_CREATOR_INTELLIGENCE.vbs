Option Explicit

Dim shell, fileSystem, repositoryRoot, pythonWindowless, command
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")

repositoryRoot = fileSystem.GetParentFolderName(WScript.ScriptFullName)
pythonWindowless = fileSystem.BuildPath(repositoryRoot, ".venv\Scripts\pythonw.exe")

If Not fileSystem.FileExists(pythonWindowless) Then
    MsgBox "Creator Intelligence is not set up yet." & vbCrLf & vbCrLf & _
        "Run SETUP_ONCE.bat, then use this launcher again.", _
        vbExclamation, "Creator Intelligence"
    WScript.Quit 1
End If

shell.CurrentDirectory = repositoryRoot
command = Chr(34) & pythonWindowless & Chr(34) & " -m creator_intelligence"
shell.Run command, 0, False
