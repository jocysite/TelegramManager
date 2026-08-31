import argparse
import os
import shutil
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


APP_NAME = "TeleManager"


def resource_path(*parts):
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, *parts)


def app_icon_path():
    return os.path.join(resource_path("assets"), "logo.ico")


def app_logo_path():
    return os.path.join(resource_path("assets"), "logo_64.png")


def payload_exe_path():
    return os.path.join(resource_path("payload"), "TeleManager.exe")


def payload_assets_path():
    return resource_path("assets")


def default_install_dir():
    local_app_data = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(local_app_data, APP_NAME)


def powershell_quote(value):
    return "'" + value.replace("'", "''") + "'"


def create_shortcut(shortcut_path, target_path, working_dir, icon_path):
    script = f"""
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut({powershell_quote(shortcut_path)})
$s.TargetPath = {powershell_quote(target_path)}
$s.WorkingDirectory = {powershell_quote(working_dir)}
$s.IconLocation = {powershell_quote(icon_path + ",0")}
$s.Description = {powershell_quote(f"{APP_NAME}")}
$s.Save()
"""
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=True,
        capture_output=True,
        text=True,
    )


def create_shortcuts(install_dir):
    target = os.path.join(install_dir, "TeleManager.exe")
    desktop = os.path.join(os.path.join(os.environ.get("USERPROFILE", ""), "Desktop"), f"{APP_NAME}.lnk")
    programs_dir = os.path.join(
        os.environ.get("APPDATA", ""),
        "Microsoft",
        "Windows",
        "Start Menu",
        "Programs",
        APP_NAME,
    )
    os.makedirs(programs_dir, exist_ok=True)
    start_menu = os.path.join(programs_dir, f"{APP_NAME}.lnk")
    create_shortcut(desktop, target, install_dir, target)
    create_shortcut(start_menu, target, install_dir, target)


def install_to(install_dir, create_shortcuts_flag=True):
    os.makedirs(install_dir, exist_ok=True)
    shutil.copy2(payload_exe_path(), os.path.join(install_dir, "TeleManager.exe"))
    assets_dst = os.path.join(install_dir, "assets")
    if os.path.exists(assets_dst):
        shutil.rmtree(assets_dst)
    shutil.copytree(payload_assets_path(), assets_dst)
    if create_shortcuts_flag:
        create_shortcuts(install_dir)


def run_silent(install_dir, create_shortcuts_flag=True):
    install_to(install_dir, create_shortcuts_flag=create_shortcuts_flag)
    print(f"Installed to {install_dir}")


class InstallerUI(tk.Tk):
    def __init__(self, install_dir):
        super().__init__()
        self.title(f"{APP_NAME} Setup")
        self.geometry("520x280")
        self.resizable(False, False)
        self.configure(bg="#0E1621")
        try:
            self.iconbitmap(app_icon_path())
        except tk.TclError:
            pass
        self.install_dir = tk.StringVar(value=install_dir)

        main = tk.Frame(self, bg="#0E1621", padx=20, pady=18)
        main.pack(fill="both", expand=True)

        try:
            self.logo = tk.PhotoImage(file=app_logo_path())
            tk.Label(main, image=self.logo, bg="#0E1621").pack(anchor="w")
        except tk.TclError:
            tk.Label(main, text=APP_NAME, fg="white", bg="#0E1621", font=("Segoe UI", 18, "bold")).pack(anchor="w")

        tk.Label(
            main,
            text="Install TeleManager to your machine and create shortcuts with the app icon.",
            bg="#0E1621",
            fg="#8A99A6",
            wraplength=470,
            justify="left",
        ).pack(anchor="w", pady=(10, 14))

        row = tk.Frame(main, bg="#0E1621")
        row.pack(fill="x", pady=(0, 12))
        tk.Entry(row, textvariable=self.install_dir, width=52).pack(side="left", fill="x", expand=True)
        tk.Button(row, text="Browse", command=self.pick_dir).pack(side="left", padx=(8, 0))

        self.status = tk.StringVar(value="Ready to install.")
        tk.Label(main, textvariable=self.status, bg="#0E1621", fg="#4CD964", anchor="w").pack(fill="x", pady=(0, 12))

        footer = tk.Frame(main, bg="#0E1621")
        footer.pack(fill="x", side="bottom")
        tk.Button(footer, text="Install", command=self.install).pack(side="right")
        tk.Button(footer, text="Cancel", command=self.destroy).pack(side="right", padx=(0, 8))

    def pick_dir(self):
        chosen = filedialog.askdirectory(initialdir=self.install_dir.get())
        if chosen:
            self.install_dir.set(chosen)

    def install(self):
        target = self.install_dir.get().strip()
        if not target:
            messagebox.showerror("Missing path", "Choose an install location first.")
            return
        self.status.set("Installing...")
        self.update_idletasks()
        try:
            install_to(target)
        except Exception as exc:
            self.status.set("Install failed.")
            messagebox.showerror("Install failed", str(exc))
            return
        self.status.set("Installed successfully.")
        messagebox.showinfo("Installed", f"{APP_NAME} installed to:\n{target}")
        self.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--silent", action="store_true")
    parser.add_argument("--no-shortcuts", action="store_true")
    parser.add_argument("--install-dir")
    args = parser.parse_args()

    install_dir = args.install_dir or default_install_dir()
    if args.silent:
        run_silent(install_dir, create_shortcuts_flag=not args.no_shortcuts)
        return

    ui = InstallerUI(install_dir)
    ui.mainloop()


if __name__ == "__main__":
    main()
