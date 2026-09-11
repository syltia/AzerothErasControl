Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = folder

check = shell.Run("cmd /c py -c ""import customtkinter, paramiko""", 0, True)
If check <> 0 Then
    shell.Run "cmd /c py -m pip install -r requirements.txt", 1, True
End If

shell.Run "pyw ember_admin.py", 0, False
