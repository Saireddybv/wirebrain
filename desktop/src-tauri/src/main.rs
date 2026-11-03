#![windows_subsystem = "windows"]
use std::{io::{BufRead, BufReader, Write}, os::windows::process::CommandExt,
    process::{Child, Command, Stdio}, sync::{mpsc, Mutex}, time::Duration};
use tauri::{menu::{CheckMenuItem, Menu, MenuItem}, tray::TrayIconBuilder,
    Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_autostart::ManagerExt;

struct Diary(Mutex<Child>);
fn show(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("diary") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}
fn notify(message: &str) {
    rfd::MessageDialog::new().set_title("Wirebrain").set_description(message).show();
}
fn control(app: &tauri::AppHandle, action: &str) {
    let diary = app.state::<Diary>();
    let mut child = diary.0.lock().unwrap();
    if child.stdin.as_mut().is_none_or(|p| writeln!(p, "{action}").is_err()) {
        notify("The diary service stopped. Quit and reopen Wirebrain.");
    }
}
fn main() {
    let result = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| show(app)))
        .plugin(tauri_plugin_autostart::Builder::new().build())
        .setup(|app| {
            let exe = app.path().resource_dir()?.join("runtime/python.exe");
            let mut child = Command::new(exe).args(["-I","-u","-m","wirebrain.desktop"])
                .env_remove("WIREBRAIN_HOME").creation_flags(0x08000000)
                .stdin(Stdio::piped()).stdout(Stdio::piped()).spawn()?;
            let stdout = child.stdout.take().unwrap();
            let (tx, rx) = mpsc::channel();
            std::thread::spawn(move || {
                let mut line = String::new();
                if BufReader::new(stdout).read_line(&mut line).is_ok() {
                    let _ = tx.send(line.trim().parse::<u16>());
                }
            });
            let port = rx.recv_timeout(Duration::from_secs(30))??;
            if port == 0 { return Err("Invalid diary port".into()); }
            app.manage(Diary(Mutex::new(child)));
            let url: tauri::Url = format!("http://127.0.0.1:{port}/").parse()?;
            let origin = url.origin();
            let window = WebviewWindowBuilder::new(app, "diary", WebviewUrl::External(url))
                .title("Wirebrain").inner_size(1080.0,760.0)
                .on_navigation(move |url| url.origin() == origin).build()?;
            let copy = window.clone();
            window.on_window_event(move |e| if let tauri::WindowEvent::CloseRequested{api,..} = e {
                api.prevent_close(); let _ = copy.hide();
            });
            let open = MenuItem::with_id(app, "open","Open diary",true,None::<&str>)?;
            let record = MenuItem::with_id(app,"record","Turn on recording…",true,None::<&str>)?;
            let pause = MenuItem::with_id(app,"pause","Pause recording",true,None::<&str>)?;
            let login = CheckMenuItem::with_id(app,"login","Open at sign-in",true,
                app.autolaunch().is_enabled()?,None::<&str>)?;
            let quit = MenuItem::with_id(app,"quit","Quit Wirebrain",true,None::<&str>)?;
            let menu = Menu::with_items(app,&[&open,&record,&pause,&login,&quit])?;
            TrayIconBuilder::new().icon(app.default_window_icon().unwrap().clone())
                .tooltip("Wirebrain · local diary").menu(&menu)
                .on_menu_event(move |app,event| match event.id.as_ref() {
                    "open" => show(app),
                    "pause" => control(app,"pause"),
                    "record" => {
                        let consent = rfd::MessageDialog::new().set_title("Turn on recording?")
                            .set_description("Wirebrain can read supported AI conversations in Chrome and desktop apps and save them on this PC. Windows may ask you to trust a local certificate and allow its capture driver. Your manual proxy will not change. Claude Desktop recording is still being tested with this capture mode.")
                            .set_buttons(rfd::MessageButtons::OkCancel).show();
                        if consent == rfd::MessageDialogResult::Ok { control(app,"record"); }
                    },
                    "login" => {
                        let manager = app.autolaunch();
                        let result = manager.is_enabled().and_then(|on| if on {manager.disable()} else {manager.enable()});
                        if result.is_err() {notify("Windows could not update the sign-in preference.");}
                        let _ = login.set_checked(manager.is_enabled().unwrap_or(false));
                    },
                    "quit" => {
                        let diary = app.state::<Diary>();
                        let mut child = diary.0.lock().unwrap();
                        drop(child.stdin.take());
                        if child.wait().is_err() {notify("Could not confirm diary shutdown.");}
                        app.exit(0);
                    },
                    _ => {}
                }).build(app)?;
            Ok(())
        }).run(tauri::generate_context!());
    if let Err(error) = result { notify(&format!("Wirebrain could not open: {error}")); }
}
