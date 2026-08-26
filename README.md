# TeleManager

<p align="center">
  <img src="assets/banner.jpg" width="420" alt="TeleManager logo"/>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.9%2B-blue.svg" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/platform-Windows-lightgrey.svg" alt="Platform: Windows">
</p>

A free, open-source desktop app for managing your own Telegram account: bulk-delete
your messages by date/time range, review and kill unauthorized sessions, set
Two-Step Verification, log a new device in without SMS, post Stories, and edit
your profile — all from one dark-themed window.

It talks to Telegram using the same official API the Telegram apps themselves
use (via [Telethon](https://github.com/LonamiWebs/Telethon)), logged in as
*you*. It never touches anyone else's account, and your credentials are
encrypted locally via your OS's own secure credential store — never shipped
in the code, never stored in plain text.

## Screenshots

<p align="center">
  <img src="assets/screenshot_setup.png" width="420" alt="Setup page"/>
  <img src="assets/screenshot_delete.png" width="420" alt="Delete Messages page"/>
</p>

## Features

- **Setup** — connect with your own Telegram API credentials; saved securely
  via Windows Credential Manager (DPAPI-encrypted, tied to your Windows user
  account and machine only)
- **Delete Messages** — remove your own messages across every chat and
  group within a specific date *and time* range, with a preview step before
  anything is deleted for real
- **Sessions & Security** — see every device logged into your account,
  terminate suspicious ones, and set/change your Two-Step Verification
  password
- **QR Login** — log a phone or tablet into your account via your PC's
  webcam, without needing an SMS code
- **Post Story** — publish a photo to your Telegram Story with a caption
  and a privacy setting (Everyone / Contacts)
- **Profile** — view and edit your name and bio
- **How To** — full in-app usage guide, including where to get your API
  credentials

## Getting started

### 1. Install dependencies

```bash
git clone https://github.com/<your-username>/TeleManager.git
cd TeleManager
pip install -r requirements.txt
```

The QR Login feature additionally needs a webcam and OpenCV, which is
already included in `requirements.txt` (`opencv-python`). If you don't plan
to use QR Login you can skip installing it.

### 2. Get your Telegram API credentials

1. Go to [my.telegram.org](https://my.telegram.org) and log in with your
   phone number.
2. Click **API development tools**.
3. Fill in any App title / short name and submit.
4. Copy the **App api_id** and **App api_hash** shown — you'll paste these
   into the app.

### 3. Run it

```bash
python telegram_manager_app.py
```

Enter your API ID, API Hash, and phone number in the Setup page and click
**Save & Connect**. The first time, Telegram sends you a login code (via the
Telegram app on another device, or SMS) — enter it in the popup. Your
credentials are then encrypted and saved locally, so next time you can just
click **Connect with Saved Credentials**.

Full instructions for every feature are also built into the app's **How To**
page.

## Security & privacy

- Your API ID/Hash/phone are encrypted via your OS's credential store
  (Windows Credential Manager, protected by DPAPI) — tied to your specific
  Windows user account and machine. They are never written to a plain text
  file and never appear anywhere in this repository's code.
- The `.session` file created after you log in (`*.session`) represents an
  active login to your account — anyone with that file has the same access
  as being logged in. It's excluded from git via `.gitignore`; **never
  commit or share it.**
- Deleting messages and terminating sessions are irreversible. Always use
  **Preview** before confirming a deletion.
- This project is not affiliated with, endorsed by, or sponsored by
  Telegram. It's an independent client built on Telegram's public API.

## Requirements

- Windows (uses Windows Credential Manager for encrypted credential
  storage, and `PrintWindow`-style Win32 behavior isn't required, but
  `keyring`'s Windows backend is)
- Python 3.9+
- A webcam, only if you want to use QR Login

## Contributing

Issues and pull requests are welcome. If you're proposing a larger change,
consider opening an issue first to discuss the approach.

## License

[MIT](LICENSE)
