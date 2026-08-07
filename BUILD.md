# BUILD.md - packaging Commerce Manager as real Windows software

There are two levels here. Do them in order.

## Level 1: a double-click .exe (no console, no visible Python)

One-time setup, in the project folder:

```
pip install pyinstaller
pip install -r requirements.txt
```

Build:

```
pyinstaller CommerceManager.spec
```

Result: `dist\CommerceManager.exe` - a single file, double-click to run,
no console window, no browser. Copy it anywhere.

**Note:** the database (`caisse.db`) is created next to wherever you put
the .exe, the first time you run it. Keep the .exe in one stable folder.

## Level 2: a real installer (Setup.exe with a wizard, Start Menu entry,
Desktop icon, uninstaller in "Add or Remove Programs")

This is what makes it feel like commercial software instead of "a file
someone sent me."

1. Do Level 1 first (`dist\CommerceManager.exe` must exist).
2. Install Inno Setup (free): https://jrsoftware.org/isdl.php
3. Open `CommerceManager.iss` in Inno Setup and click **Compile**
   (or run `ISCC.exe CommerceManager.iss` from the command line).
4. Result: `installer_output\CommerceManager-Setup.exe`

That `CommerceManager-Setup.exe` is what you'd actually hand to someone.
Running it:
- Shows a normal installer wizard
- Lets them choose to add a Desktop icon
- Adds a Start Menu entry
- Registers a proper uninstaller in Windows Settings → Apps

## Optional: a custom icon

Drop a `icon.ico` file into `assets/` (see `assets/README.txt`), then:
- Uncomment the `icon=` line in `CommerceManager.spec`
- Uncomment the `SetupIconFile=` line in `CommerceManager.iss`
- Rebuild both (Level 1 then Level 2)

## Updating the app later

Change `MyAppVersion` in `CommerceManager.iss` (e.g. "1.1"), rebuild both
levels, and distribute the new `CommerceManager-Setup.exe`. Keep
`AppId` in the .iss file exactly the same across versions - that's how
Windows knows it's an update to the same program, not a separate install.

## If something goes wrong

- **"pyinstaller is not recognized"** - close and reopen your terminal
  after installing it, or use `python -m PyInstaller` instead.
- **The .exe opens and immediately closes** - temporarily set
  `console=True` in `CommerceManager.spec`, rebuild, and run the .exe
  from a terminal so you can read the error message.
- **Antivirus flags the .exe** - common false positive for PyInstaller
  apps without a paid code-signing certificate. Add an exception. Real
  code signing (so this stops happening for everyone) costs money and
  is a separate step if you get to that stage.
- **ISCC.exe not found** - it's installed with Inno Setup, usually at
  `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`. Just opening the
  `.iss` file in the Inno Setup app and clicking Compile is easier than
  the command line.
