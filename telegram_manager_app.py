"""
Telegram Account Manager - a desktop app for managing your own Telegram
account via the Telegram API (Telethon).

Features (single window, sidebar navigation):
    - Setup: store your API credentials and log in
    - Delete Messages: remove your own messages across all chats/groups
      within a date range
    - Sessions & Security: view/terminate logged-in devices, set 2FA
    - QR Login: log another device into your account without SMS
    - Post Story: publish a photo to your Telegram Story
    - Profile: edit your name/bio
    - How To: usage instructions and where to get API credentials

Works for ANY Telegram account - enter your own credentials in the Setup
page. See the "How To" page inside the app for full instructions.

SETUP:
    pip install -r requirements.txt
    python telegram_manager_app.py

Optional (only needed for the QR Login page):
    pip install opencv-python
"""

import asyncio
import base64
import datetime
import json
import os
import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog, simpledialog, scrolledtext

import keyring
import keyring.errors
from telethon import TelegramClient, helpers
from telethon.errors import FloodWaitError
from telethon.tl.functions.account import (
    GetAuthorizationsRequest,
    ResetAuthorizationRequest,
    UpdateProfileRequest,
)
from telethon.tl.functions.auth import ImportLoginTokenRequest
from telethon.tl.functions.stories import SendStoryRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import (
    InputMediaUploadedPhoto,
    InputPeerSelf,
    InputPrivacyValueAllowAll,
    InputPrivacyValueAllowContacts,
)
from telethon.tl.types.auth import LoginTokenMigrateTo, LoginTokenSuccess

# Credentials are stored via the OS's secure credential vault (Windows
# Credential Manager, protected by DPAPI) instead of a plain file - only
# the same Windows user account on this same machine can decrypt them.
KEYRING_SERVICE = "TelegramManagerApp"
KEYRING_USERNAME = "credentials"

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def load_config():
    try:
        raw = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except keyring.errors.KeyringError:
        return {}
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def save_config(data):
    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, json.dumps(data))


def clear_config():
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass


def extract_qr_token(qr_text: str) -> bytes:
    if "token=" not in qr_text:
        raise ValueError(f"Not a Telegram login QR code: {qr_text}")
    token_b64 = qr_text.split("token=", 1)[1]
    padding = "=" * (-len(token_b64) % 4)
    return base64.urlsafe_b64decode(token_b64 + padding)


class AsyncLoop:
    """Runs an asyncio event loop on a background thread so the Tk mainloop
    never blocks on network calls."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro, on_done=None):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        if on_done:
            future.add_done_callback(on_done)
        return future

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)


# ---------------------------------------------------------------------------
# Visual design system (dark theme, matches the app's reference mockup)
# ---------------------------------------------------------------------------
COLOR_SIDEBAR = "#17212B"
COLOR_MAIN_BG = "#0E1621"
COLOR_CARD = "#17212B"
COLOR_CARD_BORDER = "#22303C"
COLOR_NAV_HOVER = "#1C2733"
COLOR_ACCENT = "#2AABEE"
COLOR_ACCENT_HOVER = "#3DB8F5"
COLOR_DANGER = "#E05353"
COLOR_TEXT_PRIMARY = "#FFFFFF"
COLOR_TEXT_SECONDARY = "#8A99A6"
COLOR_TEXT_MUTED = "#5B6B79"
COLOR_INPUT_BG = "#0E1621"
COLOR_CONSOLE_BG = "#0A0F14"
COLOR_CONSOLE_TEXT = "#8FE3A6"
COLOR_SUCCESS = "#4CD964"
COLOR_ROW_ALT = "#1C2733"
FONT_FAMILY = "Segoe UI"
FONT_MONO = "Consolas"

NAV_ITEMS = [
    ("setup", "⚙", "Setup"),
    ("delete", "\U0001F5D1", "Delete Messages"),
    ("sessions", "\U0001F6E1", "Sessions & Security"),
    ("qr", "▦", "QR Login"),
    ("story", "\U0001F5BC", "Post Story"),
    ("profile", "\U0001F464", "Profile"),
    ("help", "\U0001F4D6", "How To"),
]


def round_rectangle(canvas, x1, y1, x2, y2, radius=16, **kwargs):
    points = [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class Card(tk.Frame):
    """A rounded-corner panel. Add widgets into `card.body`, not the card
    itself - the card auto-sizes to fit whatever body contains.

    The rounded background is a canvas placed to exactly cover the card;
    `body` is a plain frame packed on top with normal padding. Using plain
    pack geometry (rather than embedding body inside the canvas as a
    window item) means body's children are laid out with real Tk size
    constraints, so they correctly shrink/wrap instead of silently
    overflowing past the card's edge.
    """

    def __init__(self, parent, radius=14, padding=18, bg=COLOR_CARD):
        super().__init__(parent, bg=parent["bg"], highlightthickness=0)
        self._bg = bg
        self._radius = radius
        self.canvas = tk.Canvas(self, bg=parent["bg"], highlightthickness=0, bd=0)
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = tk.Frame(self, bg=bg)
        self.body.pack(fill="both", expand=True, padx=padding, pady=padding)
        self.bind("<Configure>", self._redraw)

    def _redraw(self, event=None):
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 4 or h < 4:
            return
        self.canvas.delete("bg")
        round_rectangle(
            self.canvas, 1, 1, w - 1, h - 1, radius=self._radius,
            fill=self._bg, outline=COLOR_CARD_BORDER, tags="bg",
        )


class RoundedButton(tk.Canvas):
    """A canvas-drawn rounded button. style: 'primary' | 'danger-outline' |
    'secondary'."""

    def __init__(self, parent, text, command=None, style="primary",
                 width=None, height=38, radius=10, font=None):
        bg = parent["bg"]
        super().__init__(parent, height=height, bg=bg, highlightthickness=0,
                          bd=0, cursor="hand2")
        self.command = command
        self.style = style
        self.radius = radius
        self.font = font or (FONT_FAMILY, 10, "bold")
        self.text = text
        self._enabled = True

        measured = tkfont.Font(font=self.font).measure(text)
        self._width = width or max(120, measured + 48)
        self.configure(width=self._width)

        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", lambda e: self._redraw(hover=True))
        self.bind("<Leave>", lambda e: self._redraw(hover=False))
        self.bind("<Configure>", lambda e: self._redraw())
        self._redraw()

    def _palette(self, hover):
        if self.style == "primary":
            fill = COLOR_ACCENT_HOVER if hover else COLOR_ACCENT
            return fill, fill, "#FFFFFF"
        if self.style == "danger-outline":
            return None, COLOR_DANGER, COLOR_DANGER
        if self.style == "secondary":
            fill = COLOR_NAV_HOVER if hover else COLOR_CARD_BORDER
            return fill, fill, COLOR_TEXT_PRIMARY
        return COLOR_ACCENT, COLOR_ACCENT, "#FFFFFF"

    def _redraw(self, hover=False):
        self.delete("all")
        w = self.winfo_width() or self._width
        h = self.winfo_height() or int(self["height"])
        fill, outline, text_color = self._palette(hover)
        if not self._enabled:
            text_color = COLOR_TEXT_MUTED
        round_rectangle(
            self, 1, 1, w - 1, h - 1, radius=self.radius,
            fill=fill if fill else self["bg"], outline=outline, width=1.4,
        )
        self.create_text(w / 2, h / 2, text=self.text, fill=text_color, font=self.font)

    def _on_click(self, event):
        if self._enabled and self.command:
            self.command()

    def set_enabled(self, enabled):
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self._redraw()


class ScrollableFrame(tk.Frame):
    """A vertically scrollable container. Add page content into `.body` -
    used so every page can hold more than fits in the window without
    anything getting clipped; a scrollbar (and mouse wheel) appears only
    when the content is actually taller than the visible area."""

    def __init__(self, parent, bg=COLOR_MAIN_BG):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vbar.pack(side="right", fill="y")

        self.body = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")

        self.body.bind("<Configure>", self._on_body_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._on_mousewheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _on_body_configure(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self._window, width=event.width)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class NavItem(tk.Canvas):
    def __init__(self, parent, icon, text, command, width=200, height=42, radius=10):
        super().__init__(parent, width=width, height=height, bg=COLOR_SIDEBAR,
                          highlightthickness=0, bd=0, cursor="hand2")
        self.command = command
        self.icon = icon
        self.text = text
        self.radius = radius
        self.selected = False
        self.bind("<Button-1>", lambda e: self.command())
        self.bind("<Enter>", lambda e: self._redraw(hover=True))
        self.bind("<Leave>", lambda e: self._redraw(hover=False))
        self._redraw()

    def set_selected(self, selected):
        self.selected = selected
        self._redraw()

    def _redraw(self, hover=False):
        self.delete("all")
        w = int(self["width"])
        h = int(self["height"])
        if self.selected:
            round_rectangle(self, 0, 2, w, h - 2, radius=self.radius,
                             fill=COLOR_ACCENT, outline=COLOR_ACCENT)
            text_color = "#FFFFFF"
        elif hover:
            round_rectangle(self, 0, 2, w, h - 2, radius=self.radius,
                             fill=COLOR_NAV_HOVER, outline=COLOR_NAV_HOVER)
            text_color = COLOR_TEXT_PRIMARY
        else:
            text_color = COLOR_TEXT_SECONDARY
        self.create_text(20, h / 2, text=self.icon, fill=text_color, font=(FONT_FAMILY, 13), anchor="w")
        self.create_text(48, h / 2, text=self.text, fill=text_color,
                          font=(FONT_FAMILY, 10, "bold" if self.selected else "normal"), anchor="w")


class StatusPill(tk.Canvas):
    def __init__(self, parent, height=32, radius=16):
        super().__init__(parent, height=height, bg=parent["bg"], highlightthickness=0, bd=0)
        self.radius = radius
        self.connected = False
        self.text = "Not connected"
        self._font = (FONT_FAMILY, 9)
        self.configure(width=200)
        self._redraw()

    def update_status(self, text, connected):
        self.connected = connected
        self.text = text
        width = tkfont.Font(font=self._font).measure(text) + 54
        self.configure(width=max(160, width))
        self._redraw()

    def _redraw(self):
        self.delete("all")
        # Use the just-configured width, not winfo_width() - the latter can
        # still report the previous (smaller) size for one frame after a
        # resize, which let the text spill past the pill's background.
        w = int(self["width"])
        h = int(self["height"])
        round_rectangle(self, 0, 0, w, h, radius=self.radius, fill=COLOR_CARD, outline=COLOR_CARD_BORDER)
        dot_color = COLOR_SUCCESS if self.connected else COLOR_DANGER
        self.create_oval(14, h / 2 - 4, 22, h / 2 + 4, fill=dot_color, outline=dot_color)
        self.create_text(32, h / 2, text=self.text, fill=COLOR_TEXT_PRIMARY, font=self._font, anchor="w")


def styled_entry(parent, textvariable, width=30, show=None):
    entry = tk.Entry(
        parent, textvariable=textvariable, width=width, show=show,
        bg=COLOR_INPUT_BG, fg=COLOR_TEXT_PRIMARY, insertbackground=COLOR_TEXT_PRIMARY,
        relief="flat", font=(FONT_FAMILY, 10),
        highlightthickness=1, highlightbackground=COLOR_CARD_BORDER, highlightcolor=COLOR_ACCENT,
    )
    return entry


def styled_text(parent, height, width, bg=COLOR_INPUT_BG, fg=COLOR_TEXT_PRIMARY, font=None):
    return tk.Text(
        parent, height=height, width=width, bg=bg, fg=fg, insertbackground=fg,
        relief="flat", wrap="word", font=font or (FONT_FAMILY, 10),
        highlightthickness=1, highlightbackground=COLOR_CARD_BORDER, highlightcolor=COLOR_ACCENT,
    )


def card_label(parent, text, secondary=True, bold=False, size=10):
    return tk.Label(
        parent, text=text, bg=parent["bg"],
        fg=COLOR_TEXT_SECONDARY if secondary else COLOR_TEXT_PRIMARY,
        font=(FONT_FAMILY, size, "bold" if bold else "normal"),
    )


HELP_TEXT = """\
TELEGRAM ACCOUNT MANAGER - HOW TO USE

This app talks to Telegram using the same official API that the Telegram
apps themselves use (via a library called Telethon), logged in as YOU.
It can only see and act on your own account - nothing here can access
anyone else's account.

1) GETTING YOUR API CREDENTIALS (one-time, required)
   - Go to https://my.telegram.org in a browser and log in with your
     phone number.
   - Click "API development tools".
   - Fill in any App title / Short name (e.g. "MyManager") and submit.
   - You'll get an "App api_id" (a number) and "App api_hash" (a long
     string of letters/numbers). Copy both into the Setup page here.
   - These are tied to your account - do not share them or this app's
     .session file with anyone. Anyone with your .session file has full
     access to your account, same as being logged in.

2) SETUP PAGE
   - First time: enter API ID, API Hash, and your phone number (with
     country code, e.g. +15551234567) in the form, then click
     "Save & Connect".
   - Your credentials are encrypted and saved in Windows Credential
     Manager (protected by Windows DPAPI) - not as a plain text file.
     Only your own Windows user account, on this same PC, can decrypt
     them; copying them to another machine or user account won't work.
   - The form clears itself right after saving, and never re-displays a
     saved secret - next time you open the app, just click
     "Connect with Saved Credentials" instead of retyping everything.
   - To switch to a different account (or fix a typo), fill in the form
     again and click "Save & Connect" - this overwrites the old saved
     credentials with the new ones. Use "Clear Saved Credentials" to
     remove them from this machine entirely.
   - The first time you connect with a phone number, Telegram will send
     you a login code (usually via the Telegram app on another device,
     or SMS) - enter it in the popup box. If you have Two-Step
     Verification enabled, you'll also be asked for that password.
   - Once connected, the status pill at the top shows your name and a
     green dot.
   - Note: the .session file this app creates (which represents your
     active login) is still stored as a local file by the Telethon
     library and is not separately encrypted. Keep this app's folder
     private regardless - don't share it or upload it anywhere.

3) DELETE MESSAGES PAGE
   - Pick a "From date"/"From time" and "To date"/"To time" (dates as
     YYYY-MM-DD, times as HH:MM in 24-hour format, e.g. 14:30). Use the
     same date with 00:00 and 23:59 to target a whole day, or narrow the
     time fields down to target a specific window (e.g. just the messages
     sent between 2pm and 3pm).
   - Click "Preview" first - this only LISTS your messages sent in that
     range across every chat/group, without deleting anything.
   - Review the list, then click "Delete Listed Messages" and confirm.
   - Deletion uses "revoke", which removes the message for the other
     person too, not just for you. This cannot be undone.
   - Only messages YOU sent are ever touched - other people's messages
     are never deleted.

4) SESSIONS & SECURITY PAGE
   - Click "Refresh" to list every device currently logged into your
     account (this is the same list as Telegram's own
     Settings > Devices screen).
   - If you see a device you don't recognize, select it and click
     "Terminate Selected", or use "Terminate All Others" to keep only
     the session this app is using.
   - Use "Set / Change 2FA Password" to add or update your Two-Step
     Verification password. This is the single best protection against
     someone else logging into your account even if they get a login
     code. Store this password somewhere safe - Telegram cannot recover
     it for you if you forget it and have no recovery email set.

5) QR LOGIN PAGE (requires: pip install opencv-python)
   - Use this to log a phone/tablet into your account without SMS.
   - On the new device, open Telegram and tap the QR code icon on the
     phone-number screen so it displays a QR code.
   - Click "Start Scanning" here - it opens your PC's webcam. Hold the
     new device's screen up to the camera until it's recognized.
   - QR codes refresh every ~30 seconds; if one expires, let the new
     device show a fresh one and keep the scan running.

6) POST STORY PAGE
   - Choose a photo, optionally write a caption, and pick who can see it
     (Everyone or Contacts only).
   - Click "Post Story" and confirm. Note: Telegram limits how many
     stories a free (non-Premium) account can post per week - if you hit
     that limit you'll see a clear error telling you when it resets.

7) PROFILE PAGE
   - Click "Load Current" to fetch your current name/bio, edit the
     fields, then "Save Changes" to update them on Telegram.

SAFETY NOTES
   - Deleting messages and terminating sessions are NOT reversible.
     Always use Preview / review the list before confirming.
   - Never share your API hash, your login code, your 2FA password, or
     the .session file this app creates. Anyone with any of those can
     access your account.
   - Your API credentials are encrypted at rest via Windows Credential
     Manager. Your login session (.session file) is still a plain local
     file in this app's folder - keep that folder private (don't upload
     it, don't commit it to a public code repository).
"""


class TelegramManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Telegram Account Manager")
        self.geometry("900x620")
        self.minsize(700, 460)
        self.configure(bg=COLOR_MAIN_BG)
        self._set_app_icon()

        self._setup_ttk_style()

        self.async_loop = AsyncLoop()
        self.client = None
        self.connected = False
        self.ui_queue = queue.Queue()
        self.list_results = []  # cached results from the last "Preview"

        # The Setup form always starts blank, even if credentials are
        # already saved - saved secrets are never redisplayed on screen.
        self.has_saved_credentials = bool(load_config())
        self.api_id_var = tk.StringVar(value="")
        self.api_hash_var = tk.StringVar(value="")
        self.phone_var = tk.StringVar(value="")
        self.session_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Not connected")

        today = datetime.date.today().isoformat()
        self.from_date_var = tk.StringVar(value=today)
        self.from_time_var = tk.StringVar(value="00:00")
        self.to_date_var = tk.StringVar(value=today)
        self.to_time_var = tk.StringVar(value="23:59")

        self.privacy_var = tk.StringVar(value="Everyone")
        self.photo_path_var = tk.StringVar(value="")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_layout()
        self.status_var.trace_add("write", self._on_status_change)
        self._on_status_change()
        self.after(100, self._poll_queue)

    def _set_app_icon(self):
        ico_path = os.path.join(ASSETS_DIR, "logo.ico")
        png_path = os.path.join(ASSETS_DIR, "logo_64.png")
        try:
            if os.path.exists(ico_path):
                self.iconbitmap(ico_path)
            elif os.path.exists(png_path):
                self._icon_image = tk.PhotoImage(file=png_path)
                self.iconphoto(True, self._icon_image)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # ttk styling (Treeview / Combobox / Scrollbar only - everything else
    # is plain tk so it can be fully recolored)
    # ------------------------------------------------------------------
    def _setup_ttk_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(
            "Treeview",
            background=COLOR_CARD,
            fieldbackground=COLOR_CARD,
            foreground=COLOR_TEXT_PRIMARY,
            bordercolor=COLOR_CARD,
            borderwidth=0,
            rowheight=30,
            font=(FONT_FAMILY, 10),
        )
        style.map(
            "Treeview",
            background=[("selected", COLOR_ACCENT)],
            foreground=[("selected", "#FFFFFF")],
        )
        style.configure(
            "Treeview.Heading",
            background=COLOR_CARD,
            foreground=COLOR_TEXT_SECONDARY,
            borderwidth=0,
            relief="flat",
            font=(FONT_FAMILY, 10, "bold"),
        )
        style.map("Treeview.Heading", background=[("active", COLOR_CARD)])

        style.configure(
            "TCombobox",
            fieldbackground=COLOR_INPUT_BG,
            selectbackground=COLOR_INPUT_BG,
            selectforeground=COLOR_TEXT_PRIMARY,
            background=COLOR_CARD,
            foreground=COLOR_TEXT_PRIMARY,
            arrowcolor=COLOR_TEXT_PRIMARY,
            bordercolor=COLOR_CARD_BORDER,
            lightcolor=COLOR_INPUT_BG,
            darkcolor=COLOR_INPUT_BG,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", COLOR_INPUT_BG)],
            selectbackground=[("readonly", COLOR_INPUT_BG)],
            selectforeground=[("readonly", COLOR_TEXT_PRIMARY)],
            foreground=[("readonly", COLOR_TEXT_PRIMARY)],
        )
        self.option_add("*TCombobox*Listbox.background", COLOR_INPUT_BG)
        self.option_add("*TCombobox*Listbox.foreground", COLOR_TEXT_PRIMARY)
        self.option_add("*TCombobox*Listbox.selectBackground", COLOR_ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")

        style.configure(
            "Vertical.TScrollbar",
            background=COLOR_CARD_BORDER,
            troughcolor=COLOR_CARD,
            bordercolor=COLOR_CARD,
            arrowcolor=COLOR_TEXT_SECONDARY,
        )

    # ------------------------------------------------------------------
    # layout
    # ------------------------------------------------------------------
    def _build_layout(self):
        self.sidebar = tk.Frame(self, bg=COLOR_SIDEBAR, width=232)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        logo_frame = tk.Frame(self.sidebar, bg=COLOR_SIDEBAR)
        logo_frame.pack(side="top", fill="x", padx=20, pady=(24, 20))
        logo_path = os.path.join(ASSETS_DIR, "logo_32.png")
        if os.path.exists(logo_path):
            self._sidebar_logo_image = tk.PhotoImage(file=logo_path)
            tk.Label(logo_frame, image=self._sidebar_logo_image, bg=COLOR_SIDEBAR, bd=0).pack(side="left")
        else:
            logo_canvas = tk.Canvas(logo_frame, width=34, height=34, bg=COLOR_SIDEBAR, highlightthickness=0)
            logo_canvas.pack(side="left")
            logo_canvas.create_oval(1, 1, 33, 33, fill=COLOR_ACCENT, outline=COLOR_ACCENT)
            logo_canvas.create_text(17, 17, text="✈", fill="#FFFFFF", font=(FONT_FAMILY, 13))
        tk.Label(
            logo_frame, text="Telegram Account\nManager", bg=COLOR_SIDEBAR, fg=COLOR_TEXT_PRIMARY,
            font=(FONT_FAMILY, 11, "bold"), justify="left",
        ).pack(side="left", padx=(10, 0))

        nav_container = tk.Frame(self.sidebar, bg=COLOR_SIDEBAR)
        nav_container.pack(side="top", fill="x", padx=16)

        self.nav_items = {}
        self.page_titles = {}
        for key, icon, label in NAV_ITEMS:
            item = NavItem(nav_container, icon, label, command=lambda k=key: self.show_page(k))
            item.pack(side="top", fill="x", pady=3)
            self.nav_items[key] = item
            self.page_titles[key] = label

        self.main_area = tk.Frame(self, bg=COLOR_MAIN_BG)
        self.main_area.pack(side="left", fill="both", expand=True)

        header = tk.Frame(self.main_area, bg=COLOR_MAIN_BG)
        header.pack(side="top", fill="x", padx=28, pady=(26, 14))
        self.page_title_var = tk.StringVar(value="Setup")
        tk.Label(
            header, textvariable=self.page_title_var, bg=COLOR_MAIN_BG, fg=COLOR_TEXT_PRIMARY,
            font=(FONT_FAMILY, 22, "bold"),
        ).pack(side="left")
        self.status_pill = StatusPill(header)
        self.status_pill.pack(side="right", anchor="e")

        console_card = self._build_console(self.main_area)
        console_card.pack(side="bottom", fill="x", padx=28, pady=(0, 24))

        self.page_container = tk.Frame(self.main_area, bg=COLOR_MAIN_BG)
        self.page_container.pack(side="top", fill="both", expand=True, padx=28)
        self.page_container.grid_rowconfigure(0, weight=1)
        self.page_container.grid_columnconfigure(0, weight=1)

        self.pages = {}
        builders = {
            "setup": self._build_setup_page,
            "delete": self._build_delete_page,
            "sessions": self._build_sessions_page,
            "qr": self._build_qr_page,
            "story": self._build_story_page,
            "profile": self._build_profile_page,
            "help": self._build_help_page,
        }
        for key, builder in builders.items():
            page = ScrollableFrame(self.page_container)
            page.grid(row=0, column=0, sticky="nsew")
            builder(page.body)
            self.pages[key] = page

        self.show_page("setup")

    def show_page(self, name):
        # grid_remove (not just tkraise) is required here: a hidden page
        # still gridded in the shared cell would keep contributing its own
        # natural width/height to the grid's size calculation, which is
        # what caused wider hidden pages (e.g. the Sessions table) to
        # stretch/overflow the currently visible page.
        for key, page in self.pages.items():
            if key == name:
                page.grid(row=0, column=0, sticky="nsew")
            else:
                page.grid_remove()
        self.page_title_var.set(self.page_titles[name])
        for key, item in self.nav_items.items():
            item.set_selected(key == name)

    def _build_console(self, parent):
        card = Card(parent)
        row = tk.Frame(card.body, bg=COLOR_CARD)
        row.pack(side="top", fill="x")
        card_label(row, "Console", secondary=False, bold=True, size=11).pack(side="left")
        self._console_toggle_var = tk.StringVar(value="▾")
        toggle = tk.Label(
            row, textvariable=self._console_toggle_var, bg=COLOR_CARD, fg=COLOR_TEXT_SECONDARY,
            font=(FONT_FAMILY, 11), cursor="hand2",
        )
        toggle.pack(side="right")
        toggle.bind("<Button-1>", lambda e: self._toggle_console())

        self._console_body = tk.Frame(card.body, bg=COLOR_CARD)
        self._console_body.pack(side="top", fill="both", expand=True, pady=(10, 0))
        self.log_box = scrolledtext.ScrolledText(
            self._console_body, height=6, state="disabled", wrap="word",
            bg=COLOR_CONSOLE_BG, fg=COLOR_CONSOLE_TEXT, insertbackground=COLOR_CONSOLE_TEXT,
            relief="flat", font=(FONT_MONO, 9), highlightthickness=0, bd=0,
        )
        self.log_box.pack(fill="both", expand=True)
        self._console_expanded = True
        return card

    def _toggle_console(self):
        self._console_expanded = not self._console_expanded
        if self._console_expanded:
            self._console_body.pack(side="top", fill="both", expand=True, pady=(10, 0))
            self._console_toggle_var.set("▾")
        else:
            self._console_body.pack_forget()
            self._console_toggle_var.set("▴")

    def _build_setup_page(self, page):
        saved_card = Card(page)
        saved_card.pack(side="top", fill="x", pady=(0, 16))
        card_label(saved_card.body, "Saved credentials (encrypted on this machine)", secondary=False, bold=True).pack(
            side="top", anchor="w", pady=(0, 8)
        )
        self.saved_status_var = tk.StringVar(
            value=(
                "Saved credentials found on this machine."
                if self.has_saved_credentials
                else "No saved credentials on this machine yet."
            )
        )
        tk.Label(
            saved_card.body, textvariable=self.saved_status_var, bg=COLOR_CARD, fg=COLOR_TEXT_SECONDARY,
            font=(FONT_FAMILY, 10),
        ).pack(side="top", anchor="w", pady=(0, 10))
        saved_btns = tk.Frame(saved_card.body, bg=COLOR_CARD)
        saved_btns.pack(side="top", anchor="w")
        RoundedButton(saved_btns, "Connect with Saved Credentials", command=self.on_connect_saved_click).pack(
            side="left", padx=(0, 10)
        )
        RoundedButton(
            saved_btns, "Clear Saved Credentials", command=self.on_clear_saved_click, style="secondary"
        ).pack(side="left")

        form_card = Card(page)
        form_card.pack(side="top", fill="x")
        card_label(form_card.body, "Enter new credentials (replaces any saved ones)", secondary=False, bold=True).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 12)
        )

        card_label(form_card.body, "API ID").grid(row=1, column=0, sticky="e", padx=(0, 10), pady=6)
        styled_entry(form_card.body, self.api_id_var, width=36).grid(row=1, column=1, sticky="w", pady=6)

        card_label(form_card.body, "API Hash").grid(row=2, column=0, sticky="e", padx=(0, 10), pady=6)
        styled_entry(form_card.body, self.api_hash_var, width=36, show="*").grid(row=2, column=1, sticky="w", pady=6)

        card_label(form_card.body, "Phone (+countrycode...)").grid(row=3, column=0, sticky="e", padx=(0, 10), pady=6)
        styled_entry(form_card.body, self.phone_var, width=36).grid(row=3, column=1, sticky="w", pady=6)

        card_label(form_card.body, "Session file name").grid(row=4, column=0, sticky="e", padx=(0, 10), pady=6)
        styled_entry(form_card.body, self.session_var, width=36).grid(row=4, column=1, sticky="w", pady=6)

        tk.Label(
            form_card.body, text="Don't have an API ID/Hash yet? See the 'How To' page.",
            bg=COLOR_CARD, fg=COLOR_TEXT_MUTED, font=(FONT_FAMILY, 9),
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 14))

        btn_row = tk.Frame(form_card.body, bg=COLOR_CARD)
        btn_row.grid(row=6, column=0, columnspan=2, sticky="w")
        RoundedButton(btn_row, "Save & Connect", command=self.on_connect_click).pack(side="left", padx=(0, 10))
        RoundedButton(btn_row, "Disconnect", command=self.on_disconnect_click, style="secondary").pack(
            side="left", padx=(0, 10)
        )
        RoundedButton(
            btn_row, "Log Out (invalidate session)", command=self.on_logout_click, style="danger-outline"
        ).pack(side="left")

    def _build_delete_page(self, page):
        form_card = Card(page)
        form_card.pack(side="top", fill="x", pady=(0, 16))

        from_row = tk.Frame(form_card.body, bg=COLOR_CARD)
        from_row.pack(side="top", fill="x", pady=(0, 10))
        date_col1 = tk.Frame(from_row, bg=COLOR_CARD)
        date_col1.pack(side="left", padx=(0, 14))
        card_label(date_col1, "From date (YYYY-MM-DD)").pack(side="top", anchor="w", pady=(0, 4))
        styled_entry(date_col1, self.from_date_var, width=16).pack(side="top", anchor="w")
        time_col1 = tk.Frame(from_row, bg=COLOR_CARD)
        time_col1.pack(side="left")
        card_label(time_col1, "From time (HH:MM)").pack(side="top", anchor="w", pady=(0, 4))
        styled_entry(time_col1, self.from_time_var, width=8).pack(side="top", anchor="w")

        to_row = tk.Frame(form_card.body, bg=COLOR_CARD)
        to_row.pack(side="top", fill="x", pady=(0, 14))
        date_col2 = tk.Frame(to_row, bg=COLOR_CARD)
        date_col2.pack(side="left", padx=(0, 14))
        card_label(date_col2, "To date (YYYY-MM-DD)").pack(side="top", anchor="w", pady=(0, 4))
        styled_entry(date_col2, self.to_date_var, width=16).pack(side="top", anchor="w")
        time_col2 = tk.Frame(to_row, bg=COLOR_CARD)
        time_col2.pack(side="left")
        card_label(time_col2, "To time (HH:MM)").pack(side="top", anchor="w", pady=(0, 4))
        styled_entry(time_col2, self.to_time_var, width=8).pack(side="top", anchor="w")

        btn_row = tk.Frame(form_card.body, bg=COLOR_CARD)
        btn_row.pack(side="top", fill="x")
        RoundedButton(btn_row, "Preview", command=self.on_preview_click).pack(side="left")
        RoundedButton(
            btn_row, "Delete Listed Messages", command=self.on_delete_click, style="danger-outline"
        ).pack(side="right")

        table_card = Card(page)
        table_card.pack(side="top", fill="both", expand=True)
        columns = ("chat", "count")
        self.delete_tree = ttk.Treeview(table_card.body, columns=columns, show="headings", height=12)
        self.delete_tree.heading("chat", text="Chat")
        self.delete_tree.heading("count", text="Messages found")
        self.delete_tree.column("chat", width=560, stretch=True)
        self.delete_tree.column("count", width=160, anchor="center", stretch=False)
        self.delete_tree.tag_configure("odd", background=COLOR_ROW_ALT)
        self.delete_tree.pack(side="top", fill="both", expand=True)

    def _build_sessions_page(self, page):
        list_card = Card(page)
        list_card.pack(side="top", fill="x", pady=(0, 16))

        btn_row = tk.Frame(list_card.body, bg=COLOR_CARD)
        btn_row.pack(side="top", fill="x", pady=(0, 12))
        RoundedButton(btn_row, "Refresh", command=self.on_refresh_sessions_click).pack(side="left", padx=(0, 10))
        RoundedButton(
            btn_row, "Terminate Selected", command=self.on_terminate_selected_click, style="danger-outline"
        ).pack(side="left", padx=(0, 10))
        RoundedButton(
            btn_row, "Terminate All Others", command=self.on_terminate_others_click, style="danger-outline"
        ).pack(side="left")

        columns = ("app", "device", "ip", "location", "active", "current")
        self.sessions_tree = ttk.Treeview(list_card.body, columns=columns, show="headings", height=5)
        headings = {
            "app": "App",
            "device": "Device / Platform",
            "ip": "IP",
            "location": "Location",
            "active": "Last active",
            "current": "This device?",
        }
        widths = {"app": 120, "device": 170, "ip": 80, "location": 110, "active": 140, "current": 90}
        for col in columns:
            self.sessions_tree.heading(col, text=headings[col])
            self.sessions_tree.column(col, width=widths[col], anchor="w", stretch=False)
        self.sessions_tree.tag_configure("odd", background=COLOR_ROW_ALT)
        self.sessions_tree.pack(side="top", fill="x")
        self._session_auth_by_row = {}

        pw_card = Card(page)
        pw_card.pack(side="top", fill="x")
        card_label(pw_card.body, "Two-Step Verification (2FA)", secondary=False, bold=True).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 12)
        )
        card_label(pw_card.body, "Current password (blank if none set)").grid(
            row=1, column=0, sticky="e", padx=(0, 10), pady=6
        )
        self.current_pw_var = tk.StringVar()
        styled_entry(pw_card.body, self.current_pw_var, width=30, show="*").grid(row=1, column=1, sticky="w", pady=6)

        card_label(pw_card.body, "New password").grid(row=2, column=0, sticky="e", padx=(0, 10), pady=6)
        self.new_pw_var = tk.StringVar()
        styled_entry(pw_card.body, self.new_pw_var, width=30, show="*").grid(row=2, column=1, sticky="w", pady=6)

        RoundedButton(pw_card.body, "Set / Change 2FA Password", command=self.on_set_2fa_click).grid(
            row=3, column=0, columnspan=2, pady=(12, 0)
        )

    def _build_qr_page(self, page):
        card = Card(page)
        card.pack(side="top", fill="x")
        tk.Label(
            card.body,
            wraplength=760, justify="left", bg=COLOR_CARD, fg=COLOR_TEXT_SECONDARY, font=(FONT_FAMILY, 10),
            text=(
                "Log another device (phone/tablet) into your account without SMS.\n\n"
                "1. On the new device, open Telegram and tap the QR code icon on the "
                "phone-number entry screen.\n"
                "2. Click 'Start Scanning' below - it opens this PC's webcam.\n"
                "3. Hold the new device's screen up to the camera until it's detected.\n\n"
                "Requires: pip install opencv-python"
            ),
        ).pack(side="top", anchor="w", pady=(0, 16))
        RoundedButton(card.body, "Start Scanning", command=self.on_start_qr_click).pack(side="top", anchor="w")

    def _build_story_page(self, page):
        card = Card(page)
        card.pack(side="top", fill="x")

        row = tk.Frame(card.body, bg=COLOR_CARD)
        row.pack(side="top", fill="x", pady=(0, 4))
        RoundedButton(row, "Choose Image...", command=self.on_choose_photo_click, style="secondary").pack(side="left")
        tk.Label(row, textvariable=self.photo_path_var, bg=COLOR_CARD, fg=COLOR_TEXT_MUTED, font=(FONT_FAMILY, 9)).pack(
            side="left", padx=10
        )

        card_label(card.body, "Caption (optional)").pack(side="top", anchor="w", pady=(14, 6))
        self.caption_text = styled_text(card.body, height=4, width=80)
        self.caption_text.pack(side="top", anchor="w")

        row2 = tk.Frame(card.body, bg=COLOR_CARD)
        row2.pack(side="top", fill="x", pady=14)
        card_label(row2, "Visible to").pack(side="left", padx=(0, 10))
        ttk.Combobox(
            row2, textvariable=self.privacy_var, values=["Everyone", "Contacts"], state="readonly", width=14
        ).pack(side="left")

        RoundedButton(card.body, "Post Story", command=self.on_post_story_click).pack(side="top", anchor="w")

    def _build_profile_page(self, page):
        card = Card(page)
        card.pack(side="top", fill="x")

        RoundedButton(card.body, "Load Current", command=self.on_load_profile_click, style="secondary").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 16)
        )

        self.first_name_var = tk.StringVar()
        self.last_name_var = tk.StringVar()

        card_label(card.body, "First name").grid(row=1, column=0, sticky="e", padx=(0, 10), pady=6)
        styled_entry(card.body, self.first_name_var, width=36).grid(row=1, column=1, sticky="w", pady=6)
        card_label(card.body, "Last name").grid(row=2, column=0, sticky="e", padx=(0, 10), pady=6)
        styled_entry(card.body, self.last_name_var, width=36).grid(row=2, column=1, sticky="w", pady=6)
        card_label(card.body, "Bio").grid(row=3, column=0, sticky="ne", padx=(0, 10), pady=6)
        self.bio_text = styled_text(card.body, height=4, width=40)
        self.bio_text.grid(row=3, column=1, sticky="w", pady=6)

        RoundedButton(card.body, "Save Changes", command=self.on_save_profile_click).grid(
            row=4, column=0, columnspan=2, pady=(14, 0)
        )

    def _build_help_page(self, page):
        card = Card(page)
        card.pack(side="top", fill="both", expand=True)
        box = scrolledtext.ScrolledText(
            card.body, wrap="word", bg=COLOR_CARD, fg=COLOR_TEXT_SECONDARY, insertbackground=COLOR_TEXT_PRIMARY,
            relief="flat", font=(FONT_FAMILY, 10), highlightthickness=0, bd=0, height=28, width=90,
        )
        box.pack(fill="both", expand=True)
        box.insert("1.0", HELP_TEXT)
        box.configure(state="disabled")

    # ------------------------------------------------------------------
    # cross-thread plumbing
    # ------------------------------------------------------------------
    def log(self, message):
        self.ui_queue.put(("log", message))

    def _on_status_change(self, *args):
        self.status_pill.update_status(self.status_var.get(), self.connected)

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.ui_queue.get_nowait()
                if kind == "log":
                    self.log_box.configure(state="normal")
                    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
                    self.log_box.insert("end", f"[{timestamp}] {payload}\n")
                    self.log_box.see("end")
                    self.log_box.configure(state="disabled")
                elif kind == "error":
                    messagebox.showerror("Error", payload)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def ask_on_main_thread(self, prompt, hide=False):
        """Called from the background asyncio thread during login; blocks
        that thread (not the GUI) until the user answers a popup."""
        result_box = queue.Queue()

        def show():
            value = simpledialog.askstring(
                "Telegram Login", prompt, show="*" if hide else None, parent=self
            )
            result_box.put(value)

        self.after(0, show)
        value = result_box.get()
        if value is None:
            raise RuntimeError("Cancelled by user.")
        return value

    def require_connected(self):
        if not self.connected or self.client is None:
            messagebox.showwarning(
                "Not connected", "Connect to your account first in the Setup page."
            )
            return False
        return True

    def _on_close(self):
        if self.client is not None:
            try:
                self.async_loop.submit(self.client.disconnect())
            except Exception:
                pass
        self.async_loop.stop()
        self.destroy()

    # ------------------------------------------------------------------
    # Setup page handlers
    # ------------------------------------------------------------------
    async def _do_connect(self, api_id, api_hash, phone, session_name):
        client = TelegramClient(session_name, api_id, api_hash)
        await client.start(
            phone=phone,
            code_callback=lambda: self.ask_on_main_thread(
                "Enter the login code Telegram sent you:"
            ),
            password=lambda: self.ask_on_main_thread(
                "Enter your Two-Step Verification password:", hide=True
            ),
        )
        me = await client.get_me()
        return client, me

    def _connect(self, api_id, api_hash, phone, session_name):
        self.log("Connecting...")
        self.status_var.set("Connecting...")

        def on_done(future):
            try:
                client, me = future.result()
            except Exception as e:
                self.ui_queue.put(("error", f"Could not connect: {e}"))
                self.status_var.set("Not connected")
                return
            self.client = client
            self.connected = True
            name = f"{me.first_name or ''} {me.last_name or ''}".strip()
            self.status_var.set(f"Connected as {name} (@{me.username})")
            self.log(f"Connected as {name}")

        self.async_loop.submit(
            self._do_connect(api_id, api_hash, phone, session_name), on_done
        )

    def on_connect_click(self):
        try:
            api_id = int(self.api_id_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid input", "API ID must be a number.")
            return
        api_hash = self.api_hash_var.get().strip()
        phone = self.phone_var.get().strip()
        session_name = self.session_var.get().strip() or "telegram_manager_session"

        if not api_hash or not phone:
            messagebox.showerror("Missing info", "Fill in API ID, API Hash and Phone.")
            return

        save_config(
            {
                "api_id": api_id,
                "api_hash": api_hash,
                "phone": phone,
                "session_name": session_name,
            }
        )
        self.has_saved_credentials = True
        self.saved_status_var.set("Saved credentials found on this machine.")
        self.log("Credentials saved securely on this machine (Windows Credential Manager).")

        # Never leave secrets sitting in the form once they're saved.
        self.api_id_var.set("")
        self.api_hash_var.set("")
        self.phone_var.set("")
        self.session_var.set("")

        self._connect(api_id, api_hash, phone, session_name)

    def on_connect_saved_click(self):
        config = load_config()
        if not config:
            messagebox.showinfo(
                "No saved credentials",
                "Nothing saved yet on this machine - fill in the form below and "
                "click 'Save & Connect'.",
            )
            return
        try:
            api_id = int(config["api_id"])
            api_hash = config["api_hash"]
            phone = config["phone"]
            session_name = config.get("session_name") or "telegram_manager_session"
        except (KeyError, ValueError, TypeError):
            messagebox.showerror(
                "Corrupted data", "Saved credentials look invalid - please re-enter them."
            )
            return
        self._connect(api_id, api_hash, phone, session_name)

    def on_clear_saved_click(self):
        if not self.has_saved_credentials:
            return
        if not messagebox.askyesno(
            "Clear saved credentials",
            "This removes your saved API ID/Hash/phone from this machine's secure "
            "storage. It does not delete your Telegram account or log you out "
            "elsewhere. Continue?",
        ):
            return
        clear_config()
        self.has_saved_credentials = False
        self.saved_status_var.set("No saved credentials on this machine yet.")
        self.log("Saved credentials cleared.")

    def on_disconnect_click(self):
        if self.client is None:
            return

        def on_done(future):
            self.connected = False
            self.status_var.set("Not connected")
            self.log("Disconnected.")

        self.async_loop.submit(self.client.disconnect(), on_done)

    def on_logout_click(self):
        if not self.require_connected():
            return
        if not messagebox.askyesno(
            "Log out",
            "This invalidates the current login session - you'll need the login "
            "code again next time. Continue?",
        ):
            return

        def on_done(future):
            try:
                future.result()
            except Exception as e:
                self.ui_queue.put(("error", str(e)))
                return
            self.connected = False
            self.client = None
            self.status_var.set("Not connected")
            self.log("Logged out.")

        self.async_loop.submit(self.client.log_out(), on_done)

    # ------------------------------------------------------------------
    # Delete Messages page handlers
    # ------------------------------------------------------------------
    def _parse_datetime_range(self):
        try:
            from_dt = datetime.datetime.strptime(
                f"{self.from_date_var.get().strip()} {self.from_time_var.get().strip()}",
                "%Y-%m-%d %H:%M",
            )
            to_dt = datetime.datetime.strptime(
                f"{self.to_date_var.get().strip()} {self.to_time_var.get().strip()}",
                "%Y-%m-%d %H:%M",
            )
        except ValueError:
            messagebox.showerror(
                "Invalid date/time",
                "Use the format YYYY-MM-DD for dates and HH:MM (24-hour) for times.",
            )
            return None
        if from_dt > to_dt:
            messagebox.showerror(
                "Invalid range", "The 'From' date/time must not be after the 'To' date/time."
            )
            return None
        return from_dt, to_dt

    async def _do_list_messages(self, from_dt, to_dt):
        results = []
        async for dialog in self.client.iter_dialogs():
            matches = []
            async for message in self.client.iter_messages(dialog.id, from_user="me"):
                msg_local_dt = message.date.astimezone().replace(tzinfo=None)
                if from_dt <= msg_local_dt <= to_dt:
                    matches.append(message)
                elif msg_local_dt < from_dt:
                    break
            if matches:
                results.append((dialog.name, dialog.id, matches))
        return results

    def on_preview_click(self):
        if not self.require_connected():
            return
        parsed = self._parse_datetime_range()
        if not parsed:
            return
        from_dt, to_dt = parsed
        self.log(f"Listing your messages from {from_dt} to {to_dt}...")

        def on_done(future):
            try:
                results = future.result()
            except Exception as e:
                self.ui_queue.put(("error", str(e)))
                return
            self.list_results = results
            for row in self.delete_tree.get_children():
                self.delete_tree.delete(row)
            total = 0
            for i, (name, dialog_id, matches) in enumerate(results):
                tag = "odd" if i % 2 else ""
                self.delete_tree.insert("", "end", values=(f"\U0001F4AC  {name}", len(matches)), tags=(tag,))
                total += len(matches)
            self.log(f"Found {total} message(s) across {len(results)} chat(s).")

        self.async_loop.submit(self._do_list_messages(from_dt, to_dt), on_done)

    async def _do_delete_messages(self, matches_by_dialog):
        total_deleted = 0
        for _name, dialog_id, matches in matches_by_dialog:
            for m in matches:
                try:
                    await self.client.delete_messages(dialog_id, m.id, revoke=True)
                except FloodWaitError as e:
                    self.log(f"Rate limited, waiting {e.seconds}s...")
                    await asyncio.sleep(e.seconds)
                    await self.client.delete_messages(dialog_id, m.id, revoke=True)
                total_deleted += 1
                await asyncio.sleep(0.5)
        return total_deleted

    def on_delete_click(self):
        if not self.require_connected():
            return
        if not self.list_results:
            messagebox.showinfo("Nothing to delete", "Click 'Preview' first.")
            return
        total = sum(len(matches) for _n, _i, matches in self.list_results)
        if not messagebox.askyesno(
            "Confirm deletion",
            f"This will PERMANENTLY delete {total} message(s) for both you and "
            f"the recipients, across {len(self.list_results)} chat(s). "
            f"This cannot be undone. Continue?",
        ):
            return

        self.log(f"Deleting {total} message(s)...")

        def on_done(future):
            try:
                deleted = future.result()
            except Exception as e:
                self.ui_queue.put(("error", str(e)))
                return
            self.log(f"Done: deleted {deleted} message(s).")
            self.list_results = []
            for row in self.delete_tree.get_children():
                self.delete_tree.delete(row)

        self.async_loop.submit(self._do_delete_messages(self.list_results), on_done)

    # ------------------------------------------------------------------
    # Sessions & Security page handlers
    # ------------------------------------------------------------------
    def on_refresh_sessions_click(self):
        if not self.require_connected():
            return

        def on_done(future):
            try:
                result = future.result()
            except Exception as e:
                self.ui_queue.put(("error", str(e)))
                return
            for row in self.sessions_tree.get_children():
                self.sessions_tree.delete(row)
            self._session_auth_by_row = {}
            for i, auth in enumerate(result.authorizations):
                tag = "odd" if i % 2 else ""
                row_id = self.sessions_tree.insert(
                    "",
                    "end",
                    values=(
                        f"{auth.app_name} {auth.app_version}",
                        f"{auth.device_model} / {auth.platform} {auth.system_version}",
                        auth.ip,
                        auth.country,
                        str(auth.date_active),
                        "Yes" if auth.current else "No",
                    ),
                    tags=(tag,),
                )
                self._session_auth_by_row[row_id] = auth
            self.log(f"Found {len(result.authorizations)} active session(s).")

        self.async_loop.submit(self.client(GetAuthorizationsRequest()), on_done)

    async def _terminate(self, auth_hashes):
        for h in auth_hashes:
            await self.client(ResetAuthorizationRequest(hash=h))

    def on_terminate_selected_click(self):
        if not self.require_connected():
            return
        selected = self.sessions_tree.selection()
        if not selected:
            messagebox.showinfo("Nothing selected", "Select one or more sessions first.")
            return
        auths = [self._session_auth_by_row[r] for r in selected if r in self._session_auth_by_row]
        auths = [a for a in auths if not a.current]
        if not auths:
            messagebox.showinfo("Nothing to do", "You can't terminate the current session here.")
            return
        if not messagebox.askyesno(
            "Confirm", f"Terminate {len(auths)} selected session(s)?"
        ):
            return

        def on_done(future):
            try:
                future.result()
            except Exception as e:
                self.ui_queue.put(("error", str(e)))
                return
            self.log(f"Terminated {len(auths)} session(s).")
            self.on_refresh_sessions_click()

        self.async_loop.submit(self._terminate([a.hash for a in auths]), on_done)

    def on_terminate_others_click(self):
        if not self.require_connected():
            return
        auths = [a for a in self._session_auth_by_row.values() if not a.current]
        if not auths:
            messagebox.showinfo("Nothing to do", "Click 'Refresh' first, or no other sessions exist.")
            return
        if not messagebox.askyesno(
            "Confirm", f"Terminate ALL {len(auths)} other session(s)? This logs out every device except this one."
        ):
            return

        def on_done(future):
            try:
                future.result()
            except Exception as e:
                self.ui_queue.put(("error", str(e)))
                return
            self.log(f"Terminated {len(auths)} other session(s).")
            self.on_refresh_sessions_click()

        self.async_loop.submit(self._terminate([a.hash for a in auths]), on_done)

    def on_set_2fa_click(self):
        if not self.require_connected():
            return
        new_password = self.new_pw_var.get()
        current_password = self.current_pw_var.get() or None
        if not new_password:
            messagebox.showerror("Missing password", "Enter a new password.")
            return

        def on_done(future):
            try:
                future.result()
            except Exception as e:
                self.ui_queue.put(("error", str(e)))
                return
            self.log("2FA password updated. Store it somewhere safe.")
            self.new_pw_var.set("")
            self.current_pw_var.set("")

        self.async_loop.submit(
            self.client.edit_2fa(current_password=current_password, new_password=new_password),
            on_done,
        )

    # ------------------------------------------------------------------
    # QR Login page handler
    # ------------------------------------------------------------------
    async def _do_qr_login(self):
        try:
            import cv2
        except ImportError:
            raise RuntimeError("Run: pip install opencv-python")

        detector = cv2.QRCodeDetector()
        cap = cv2.VideoCapture(0)
        seen = set()
        self.log("Webcam opened. Hold the phone's QR code up to it (press 'q' to cancel)...")
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    raise RuntimeError("Could not read from webcam.")
                data, _points, _ = detector.detectAndDecode(frame)
                cv2.imshow("Scan the Telegram QR code (press q to cancel)", frame)

                if data and data.startswith("tg://login") and data not in seen:
                    seen.add(data)
                    self.log("QR code detected, verifying...")
                    token = extract_qr_token(data)
                    result = await self.client(ImportLoginTokenRequest(token=token))
                    while isinstance(result, LoginTokenMigrateTo):
                        await self.client._switch_dc(result.dc_id)
                        result = await self.client(ImportLoginTokenRequest(token=result.token))
                    if isinstance(result, LoginTokenSuccess):
                        return "The other device is now logged in."
                    return f"Unexpected result: {result}"

                if cv2.waitKey(1) & 0xFF == ord("q"):
                    return "Cancelled."
                await asyncio.sleep(0.01)
        finally:
            cap.release()
            cv2.destroyAllWindows()

    def on_start_qr_click(self):
        if not self.require_connected():
            return

        def on_done(future):
            try:
                message = future.result()
            except Exception as e:
                self.ui_queue.put(("error", str(e)))
                return
            self.log(message)

        self.async_loop.submit(self._do_qr_login(), on_done)

    # ------------------------------------------------------------------
    # Post Story page handlers
    # ------------------------------------------------------------------
    def on_choose_photo_click(self):
        path = filedialog.askopenfilename(
            filetypes=[("Images", "*.jpg *.jpeg *.png *.webp")]
        )
        if path:
            self.photo_path_var.set(path)

    async def _do_post_story(self, photo_path, caption, privacy_rules):
        uploaded = await self.client.upload_file(photo_path)
        media = InputMediaUploadedPhoto(file=uploaded)
        await self.client(
            SendStoryRequest(
                peer=InputPeerSelf(),
                media=media,
                privacy_rules=privacy_rules,
                caption=caption or None,
                random_id=helpers.generate_random_long(),
            )
        )

    def on_post_story_click(self):
        if not self.require_connected():
            return
        photo_path = self.photo_path_var.get().strip()
        if not photo_path:
            messagebox.showerror("Missing image", "Choose an image first.")
            return
        caption = self.caption_text.get("1.0", "end").strip()
        privacy_rules = (
            [InputPrivacyValueAllowAll()]
            if self.privacy_var.get() == "Everyone"
            else [InputPrivacyValueAllowContacts()]
        )
        if not messagebox.askyesno(
            "Confirm", f"Post this photo as a story visible to '{self.privacy_var.get()}'?"
        ):
            return

        self.log("Uploading and posting story...")

        def on_done(future):
            try:
                future.result()
            except Exception as e:
                self.ui_queue.put(("error", str(e)))
                return
            self.log("Story posted.")

        self.async_loop.submit(
            self._do_post_story(photo_path, caption, privacy_rules), on_done
        )

    # ------------------------------------------------------------------
    # Profile page handlers
    # ------------------------------------------------------------------
    async def _do_load_profile(self):
        me = await self.client.get_me()
        about = ""
        try:
            full = await self.client(GetFullUserRequest(await self.client.get_input_entity("me")))
            about = getattr(full.full_user, "about", "") or ""
        except Exception:
            pass
        return me, about

    def on_load_profile_click(self):
        if not self.require_connected():
            return

        def on_done(future):
            try:
                me, about = future.result()
            except Exception as e:
                self.ui_queue.put(("error", str(e)))
                return
            self.first_name_var.set(me.first_name or "")
            self.last_name_var.set(me.last_name or "")
            self.bio_text.delete("1.0", "end")
            self.bio_text.insert("1.0", about)
            self.log("Profile loaded.")

        self.async_loop.submit(self._do_load_profile(), on_done)

    def on_save_profile_click(self):
        if not self.require_connected():
            return
        first_name = self.first_name_var.get().strip()
        last_name = self.last_name_var.get().strip()
        about = self.bio_text.get("1.0", "end").strip()

        def on_done(future):
            try:
                future.result()
            except Exception as e:
                self.ui_queue.put(("error", str(e)))
                return
            self.log("Profile updated.")

        self.async_loop.submit(
            self.client(
                UpdateProfileRequest(first_name=first_name, last_name=last_name, about=about)
            ),
            on_done,
        )


if __name__ == "__main__":
    app = TelegramManagerApp()
    app.mainloop()
