# Windows desktop prototype

Wirebrain opens the existing diary in a Tauri window. Closing the window leaves it in the Windows notification area. **Open diary** brings it back. **Turn on recording** explains the scope before asking Windows for certificate and driver permissions. **Pause recording** stops capture without deleting memories. **Open at sign-in** is opt-in and opens the diary; it does not enable recording. **Quit Wirebrain** also stops the shell's recorder.

This is an unsigned engineering build. No Wirebrain account, extension, Node or system Python is needed by the installed app. On first launch the installer may need to provision Microsoft's WebView2 runtime. The diary uses the existing default user home (`~/.wirebrain`); it does not automatically move a separate source-checkout database. Optional FastEmbed is not bundled. Uninstall preserves diary data, requests recorder shutdown and driver recovery, removes the matching trusted root, and aborts on cleanup failure.

## Build and check

On a Windows x64 build machine with Python 3.11, Node, Rust/MSVC, Windows SDK and WebView2:

1. Run `python desktop/prepare_runtime.py` from the repo root. It requires a fresh staging directory, verifies the CPython archive digest, installs the locked capture dependencies, and installs Wirebrain into the private runtime.
2. Run `python desktop/smoke.py`. This uses a temporary diary, checks the page and stats, refuses first-time web enrollment, and confirms the server exits on parent pipe closure.
3. From `desktop`, run `npx --yes --package @tauri-apps/cli@2.12.4 tauri build --bundles nsis`. Windows CI builds, locally installs and uninstalls the unsigned candidate on a disposable runner. It does not publish an installer.

The tray owns the Python dashboard using a private pipe; it loads only the loopback port reported by its own child. The window cannot navigate outside that origin and has no Tauri command permissions. The shell uses Windows process capture only. It never requests system-proxy mode.

Before distribution: [Claude first-send investigation](https://github.com/Saireddybv/wirebrain/issues/9), [signing and reproducible builds](https://github.com/Saireddybv/wirebrain/issues/11), and installed-app acceptance tests with real consent and cleanup. [Claude Desktop 4.4212.0](https://github.com/Saireddybv/wirebrain/issues/10) has a separate process-capture coverage investigation. Older port-based capture produced completed Claude records.
