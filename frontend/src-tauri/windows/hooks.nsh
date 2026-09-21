; NSIS installer hooks for the desktop app (bundle.windows.nsis.installerHooks).
;
; The app starts a local backend, uh-backend.exe (a PyInstaller onefile build that
; runs as two processes). Tauri's installer only waits for the main executable to
; close, so a backend still running from the previous version keeps its files
; locked and the update cannot replace them. Stop it before files are copied.

!macro NSIS_HOOK_PREINSTALL
  nsExec::Exec '"$SYSDIR\taskkill.exe" /F /T /IM uh-backend.exe'
  Pop $0
  Sleep 500
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  nsExec::Exec '"$SYSDIR\taskkill.exe" /F /T /IM uh-backend.exe'
  Pop $0
  Sleep 500
!macroend
