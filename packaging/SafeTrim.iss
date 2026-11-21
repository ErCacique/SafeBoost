; Instalador de SafeTrim · Inno Setup 6
; Lo compila release.yml a partir de dist\SafeTrim (PyInstaller onedir):
;   iscc /DAppVersion=0.5.0 packaging\SafeTrim.iss
; Resultado: dist\SafeTrim-Setup-<versión>.exe

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; AppId fijo: identifica la instalación para actualizar y desinstalar. No cambiarlo nunca.
AppId={{86C1CB48-73C9-4787-AFB6-B5B74BC5F720}
AppName=SafeTrim
AppVersion={#AppVersion}
AppVerName=SafeTrim {#AppVersion}
AppPublisher=ErCacique
AppPublisherURL=https://github.com/ErCacique/WinOpt
DefaultDirName={autopf}\SafeTrim
DefaultGroupName=SafeTrim
DisableProgramGroupPage=yes
; SafeTrim siempre se ejecuta como administrador: la instalación también es para todo el equipo.
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19045
OutputDir=..\dist
OutputBaseFilename=SafeTrim-Setup-{#AppVersion}
SetupIconFile=..\assets\safetrim.ico
UninstallDisplayIcon={app}\SafeTrim.exe
UninstallDisplayName=SafeTrim
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Si SafeTrim está abierto, se pide cerrarlo antes de actualizar.
CloseApplications=yes
VersionInfoVersion={#AppVersion}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; Flags: unchecked

[Files]
Source: "..\dist\SafeTrim\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\SafeTrim"; Filename: "{app}\SafeTrim.exe"
; Kit de rescate: deshace todas las sesiones aunque la interfaz no arranque (también en modo seguro).
Name: "{group}\SafeTrim - Deshacer todos los cambios"; Filename: "{app}\SafeTrim.exe"; Parameters: "--undo-all"
Name: "{autodesktop}\SafeTrim"; Filename: "{app}\SafeTrim.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SafeTrim.exe"; Description: "Abrir SafeTrim"; Flags: nowait postinstall skipifsilent shellexec

[UninstallRun]
; Quita la tarea temporal de medición tras reiniciar si quedó programada. Los datos
; (%LOCALAPPDATA%\SafeTrim: sesiones para deshacer, copias .reg, logs) se conservan a propósito.
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""\SafeTrim\PostRebootMetrics"" /F"; Flags: runhidden; RunOnceId: "DelSafeTrimTask"
