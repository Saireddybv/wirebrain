!macro NSIS_HOOK_PREUNINSTALL
  nsExec::ExecToStack '"$INSTDIR\runtime\python.exe" -I -m wirebrain.desktop_cleanup'
  Pop $0
  Pop $1
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "Wirebrain could not confirm capture cleanup. Close Wirebrain and retry uninstall. Your diary is preserved."
    Abort
  ${EndIf}
!macroend
