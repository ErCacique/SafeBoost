; Instalador de SafeBoost · Inno Setup 6
; Lo compila release.yml a partir de dist\SafeBoost (PyInstaller onedir):
;   iscc /DAppVersion=0.5.0 packaging\SafeBoost.iss
; Resultado: dist\SafeBoost-Setup-<versión>.exe

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; AppId fijo: identifica la instalación para actualizar y desinstalar. No cambiarlo nunca.
AppId={{86C1CB48-73C9-4787-AFB6-B5B74BC5F720}
AppName=SafeBoost
AppVersion={#AppVersion}
AppVerName=SafeBoost {#AppVersion}
AppPublisher=ErCacique
AppPublisherURL=https://github.com/ErCacique/WinOpt
DefaultDirName={autopf}\SafeBoost
DefaultGroupName=SafeBoost
DisableProgramGroupPage=yes
; Hasta 0.10.x el programa se llamaba SafeTrim (C:\Program Files\SafeTrim). Con el mismo AppId,
; Inno reutilizaría esa carpeta y ese grupo: se instala en la carpeta nueva y se borra la antigua.
UsePreviousAppDir=no
UsePreviousGroup=no
; SafeBoost siempre se ejecuta como administrador: la instalación también es para todo el equipo.
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19045
OutputDir=..\dist
OutputBaseFilename=SafeBoost-Setup-{#AppVersion}
SetupIconFile=..\assets\safeboost.ico
UninstallDisplayIcon={app}\SafeBoost.exe
UninstallDisplayName=SafeBoost
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Si SafeBoost está abierto, se pide cerrarlo antes de actualizar.
CloseApplications=yes
VersionInfoVersion={#AppVersion}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; Flags: unchecked

[InstallDelete]
; Restos de SafeTrim (nombre anterior). Los datos del usuario (%LOCALAPPDATA%) no se tocan: el
; programa los copia a SafeBoost al arrancar.
Type: filesandordirs; Name: "{autopf}\SafeTrim"
Type: filesandordirs; Name: "{commonprograms}\SafeTrim"
Type: files; Name: "{commondesktop}\SafeTrim.lnk"

[Files]
Source: "..\dist\SafeBoost\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\SafeBoost"; Filename: "{app}\SafeBoost.exe"
; Kit de rescate: deshace todas las sesiones aunque la interfaz no arranque (también en modo seguro).
Name: "{group}\SafeBoost - Deshacer todos los cambios"; Filename: "{app}\SafeBoost.exe"; Parameters: "--undo-all"
Name: "{autodesktop}\SafeBoost"; Filename: "{app}\SafeBoost.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SafeBoost.exe"; Description: "Abrir SafeBoost"; Flags: nowait postinstall skipifsilent shellexec
; Actualización automática desde SafeTrim (instalación silenciosa): el reinicio que pide
; SafeTrim apuntaría al .exe antiguo, que ya no existe; se abre el nuevo.
Filename: "{app}\SafeBoost.exe"; Flags: nowait shellexec; Check: WizardSilent and CameFromSafeTrim

[UninstallRun]
; Quita la tarea temporal de medición tras reiniciar si quedó programada. Los datos
; (%LOCALAPPDATA%\SafeBoost: sesiones para deshacer, copias .reg, logs) se conservan a propósito.
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""\SafeBoost\PostRebootMetrics"" /F"; Flags: runhidden; RunOnceId: "DelSafeBoostTask"
; Tareas opcionales (mantenimiento mensual y vigilancia): sin el programa no tienen sentido.
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""\SafeBoost\Maintenance"" /F"; Flags: runhidden; RunOnceId: "DelSafeBoostMaint"
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""\SafeBoost\Tray"" /F"; Flags: runhidden; RunOnceId: "DelSafeBoostTray"

[Code]
var
  SafeTrimFound: Boolean;

function InitializeSetup(): Boolean;
begin
  SafeTrimFound := FileExists(ExpandConstant('{autopf}\SafeTrim\SafeTrim.exe'));
  Result := True;
end;

function CameFromSafeTrim(): Boolean;
begin
  Result := SafeTrimFound;
end;
