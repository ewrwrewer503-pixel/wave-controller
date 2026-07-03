import tkinter as tk
from tkinter import filedialog, messagebox
import subprocess
import threading
import time
import os
import sys
import ctypes
import winreg  # only works on windows, that's fine since this whole thing is windows-only anyway

try:
    import pygetwindow as gw
    HAVE_GW = True
except ImportError:
    HAVE_GW = False
    # not fatal, we just won't be able to restore focus after relaunch

try:
    import pystray
    from PIL import Image, ImageDraw
    HAVE_TRAY = True
except ImportError:
    HAVE_TRAY = False
    # not fatal, we just won't have a system tray icon

APP_NAME = "WaveController"  # used as the key name in the registry Run key

CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".wavecontroller_config")

# --- COMMON INSTALL LOCATIONS TO TRY IF NO PATH IS SAVED YET ---
DEFAULT_PATH_GUESSES = [
    "C:/Program Files/Wave/Wave.exe",
    "C:/Program Files (x86)/Wave/Wave.exe",
]


# ------------------------------------------------------------------
# SINGLE INSTANCE LOCK
# ------------------------------------------------------------------
def acquire_single_instance_lock():
    """Uses a named Windows mutex so a second copy can't run at once.
    Returns True if this is the only instance, False if another is already running."""
    mutex_name = "Global\\WaveControllerSingleInstanceMutex"
    ERROR_ALREADY_EXISTS = 183
    ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
    return ctypes.GetLastError() != ERROR_ALREADY_EXISTS


# ------------------------------------------------------------------
# CONFIG PERSISTENCE (path, delay, last on/off state)
# ------------------------------------------------------------------
def load_config():
    # format: line1=path, line2=delay, line3=was_running ("1"/"0")
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                lines = f.read().splitlines()
            path = lines[0] if len(lines) > 0 else ""
            delay = lines[1] if len(lines) > 1 else "120"
            was_running = (lines[2] == "1") if len(lines) > 2 else False
            return path, delay, was_running
        except Exception:
            pass

    # no config yet - try to auto-detect a common install location
    for guess in DEFAULT_PATH_GUESSES:
        if os.path.exists(guess):
            return guess, "120", False
    return "", "120", False


def save_config(path, delay, was_running):
    try:
        with open(CONFIG_FILE, "w") as f:
            f.write(path + "\n" + delay + "\n" + ("1" if was_running else "0") + "\n")
    except Exception:
        pass  # not critical if this fails


def is_in_startup():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                              r"Software\Microsoft\Windows\CurrentVersion\Run",
                              0, winreg.KEY_READ)
        winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


def set_startup(enabled):
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
    if enabled:
        # figure out how to relaunch ourselves - if frozen (exe) use that, otherwise
        # call python with this script's path
        if getattr(sys, "frozen", False):
            cmd = f'"{sys.executable}"'
        else:
            script = os.path.abspath(__file__)
            cmd = f'"{sys.executable}" "{script}"'
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
    else:
        try:
            winreg.DeleteValue(key, APP_NAME)
        except FileNotFoundError:
            pass
    winreg.CloseKey(key)


def make_tray_image(color):
    """Draws a simple filled circle icon for the system tray - no external
    image file needed."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, size - 4, size - 4), fill=color)
    return img


class WaveManagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Wave Controller")
        self.root.geometry("450x300")
        self.root.resizable(False, False)

        self.is_running = False
        self.current_process = None
        self.loop_thread = None
        self.tray_icon = None

        saved_path, saved_delay, was_running = load_config()

        self.exe_path = tk.StringVar(value=saved_path or "C:/Program Files/Wave/Wave.exe")
        self.delay_seconds = tk.StringVar(value=saved_delay)
        self.startup_var = tk.BooleanVar(value=is_in_startup())

        self.build_ui()

        # handle the window's X button - minimize to tray instead of quitting,
        # so the automation loop keeps running quietly in the background
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

        if HAVE_TRAY:
            self.start_tray_icon()

        # resume whatever state the app was in last time it closed, rather
        # than always forcing it on just because the path exists
        self._pending_resume = was_running
        self.root.after(300, self.autostart)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def build_ui(self):
        path_frame = tk.LabelFrame(self.root, text=" Application Settings ", padx=10, pady=10)
        path_frame.pack(fill="x", padx=15, pady=10)

        tk.Label(path_frame, text="Wave.exe Path:").grid(row=0, column=0, sticky="w")
        self.path_entry = tk.Entry(path_frame, textvariable=self.exe_path, width=35)
        self.path_entry.grid(row=0, column=1, padx=5)
        tk.Button(path_frame, text="Browse", command=self.browse_file).grid(row=0, column=2)

        tk.Label(path_frame, text="Delay (Seconds):").grid(row=1, column=0, sticky="w", pady=(10, 0))
        vcmd = (self.root.register(self._validate_digits), "%P")
        self.delay_entry = tk.Entry(path_frame, textvariable=self.delay_seconds, width=10,
                                     validate="key", validatecommand=vcmd)
        self.delay_entry.grid(row=1, column=1, sticky="w", padx=5, pady=(10, 0))

        self.startup_check = tk.Checkbutton(
            path_frame, text="Run automatically when Windows starts",
            variable=self.startup_var, command=self.on_startup_toggle
        )
        self.startup_check.grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))

        control_frame = tk.Frame(self.root)
        control_frame.pack(pady=15)

        self.status_label = tk.Label(control_frame, text="Status: STOPPED", fg="red",
                                      font=("Arial", 10, "bold"))
        self.status_label.pack(side="left", padx=10)

        self.toggle_btn = tk.Button(control_frame, text="Turn ON", bg="green", fg="white",
                                     font=("Arial", 11, "bold"), width=12, command=self.toggle_state)
        self.toggle_btn.pack(side="left", padx=10)

        hint = "Closing this window keeps it running in the system tray."
        if not HAVE_TRAY:
            hint = "Tip: install 'pystray' and 'pillow' to enable a tray icon."
        tk.Label(self.root, text=hint, fg="gray", font=("Arial", 8)).pack(side="bottom", pady=(0, 8))

    def _validate_digits(self, proposed):
        return proposed == "" or proposed.isdigit()

    def on_startup_toggle(self):
        try:
            set_startup(self.startup_var.get())
        except Exception as e:
            messagebox.showerror("Startup Error", f"Couldn't update startup setting:\n{e}")
            # flip the checkbox back since it didn't actually work
            self.startup_var.set(not self.startup_var.get())

    def browse_file(self):
        filename = filedialog.askopenfilename(
            title="Select Wave.exe",
            filetypes=[("Executable Files", "*.exe"), ("All Files", "*.*")]
        )
        if filename:
            self.exe_path.set(filename)

    # ------------------------------------------------------------------
    # TRAY ICON
    # ------------------------------------------------------------------
    def start_tray_icon(self):
        menu = pystray.Menu(
            pystray.MenuItem("Show Wave Controller", self.show_from_tray, default=True),
            pystray.MenuItem("Turn On/Off", lambda: self.root.after(0, self.toggle_state)),
            pystray.MenuItem("Exit", self.quit_app),
        )
        self.tray_icon = pystray.Icon(
            APP_NAME, make_tray_image("red"), "Wave Controller (stopped)", menu
        )
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def update_tray_icon(self):
        if not self.tray_icon:
            return
        if self.is_running:
            self.tray_icon.icon = make_tray_image("green")
            self.tray_icon.title = "Wave Controller (running)"
        else:
            self.tray_icon.icon = make_tray_image("red")
            self.tray_icon.title = "Wave Controller (stopped)"

    def hide_to_tray(self):
        if HAVE_TRAY:
            self.root.withdraw()
        else:
            # no tray support available, so just minimize instead of hiding completely
            self.root.iconify()

    def show_from_tray(self, icon=None, item=None):
        self.root.after(0, self.root.deiconify)
        self.root.after(0, self.root.lift)

    def quit_app(self, icon=None, item=None):
        self.is_running = False
        save_config(self.exe_path.get(), self.delay_seconds.get(), False)
        if self.current_process and self.current_process.poll() is None:
            try:
                self.current_process.kill()
            except Exception:
                pass
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.after(0, self.root.destroy)

    # ------------------------------------------------------------------
    # AUTOMATION
    # ------------------------------------------------------------------
    def autostart(self):
        # only resume automatically if the path is valid AND that's the state
        # the app was left in last time (don't force it on just because it can)
        if self._pending_resume and os.path.exists(self.exe_path.get()):
            self.toggle_state()

    def toggle_state(self):
        if not self.is_running:
            try:
                int(self.delay_seconds.get() or "0")
            except ValueError:
                messagebox.showerror("Error", "Please enter a valid number for seconds.")
                return

            if not os.path.exists(self.exe_path.get()):
                messagebox.showerror("Error", "That Wave.exe path doesn't exist. Double check it.")
                return

            save_config(self.exe_path.get(), self.delay_seconds.get(), True)

            self.is_running = True
            self.toggle_btn.config(text="Turn OFF", bg="red")
            self.status_label.config(text="Status: RUNNING", fg="green")
            self.set_inputs_enabled(False)
            self.update_tray_icon()

            self.loop_thread = threading.Thread(target=self.automation_loop, daemon=True)
            self.loop_thread.start()
        else:
            self.is_running = False
            self.toggle_btn.config(text="Turn ON", bg="green")
            self.status_label.config(text="Status: STOPPED", fg="red")
            self.set_inputs_enabled(True)
            self.update_tray_icon()
            save_config(self.exe_path.get(), self.delay_seconds.get(), False)

    def set_inputs_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        self.path_entry.config(state=state)
        self.delay_entry.config(state=state)

    def automation_loop(self):
        path = self.exe_path.get()

        try:
            self.current_process = subprocess.Popen(path)
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Launch Error", f"Could not open Wave: {e}"))
            self.root.after(0, self.toggle_state)
            return

        while self.is_running:
            try:
                previous_window = gw.getActiveWindow() if HAVE_GW else None

                if self.current_process and self.current_process.poll() is None:
                    self.current_process.kill()
                    self.current_process.wait()

                time.sleep(2)
                if not self.is_running:
                    break

                self.current_process = subprocess.Popen(path)
                time.sleep(1.5)

                if previous_window:
                    try:
                        previous_window.activate()
                    except Exception:
                        pass  # window might've closed, whatever

                if not self.is_running:
                    break

                delay = int(self.delay_seconds.get())
                for _ in range(delay):
                    if not self.is_running:
                        break
                    time.sleep(1)

            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Execution Error", str(e)))
                self.root.after(0, self.toggle_state)
                break


if __name__ == "__main__":
    if not acquire_single_instance_lock():
        # another copy is already running - just bring attention to that instead
        # of launching a duplicate that would fight over the same process
        try:
            ctypes.windll.user32.MessageBoxW(
                0,
                "Wave Controller is already running.\nCheck your system tray.",
                "Already Running",
                0x40,
            )
        except Exception:
            pass
        sys.exit(0)

    root = tk.Tk()
    app = WaveManagerApp(root)
    root.mainloop()
