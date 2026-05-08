# Tailscale GUI (Linux)

A desktop GUI wrapper for the `tailscale` CLI with focus on:

- Fast connect/disconnect
- Easy exit-node switching
- Device list view (clients in your tailnet)
- Advanced command box for any CLI option

## Features

- Dashboard with local node status
- Buttons for `up`, `down`, `login`, `web`
- Devices table showing online status, OS, and exit-node capability
- Exit-node selector with optional LAN access setting
- Advanced tab where you can run any `tailscale` command arguments
- Polished black-and-white theme with improved spacing and monochrome icons
- Real system tray icon with quick menu: show/hide, connect, disconnect, refresh, exit-node selection, quit
- Professional network-based logo with lock accent for security

## Design

- **Color Scheme**: Black background with white text and green success/red error feedback
- **Logo**: Network nodes with central lock accent representing secure connectivity
- **Theme**: Compact portrait window (420×560 px) designed for quick access and minimal screen usage
- **Icons**: Scalable SVG logo used in window decoration, system tray, desktop launcher, and application menus

## Requirements

- Linux desktop with Python 3.10+
- Tailscale installed and daemon running
- `tailscale` command available in your `PATH`
- For tray/appet support: `pystray` and `Pillow` (installed via `requirements.txt`)

## Run

```bash
python3 app.py
```

Or use the launcher helper:

```bash
./run.sh
```

## Add To App Menu / Desktop Applets

Install a local desktop launcher (no root required):

```bash
chmod +x install-desktop.sh
./install-desktop.sh
```

The installer also installs Python tray dependencies for your user account with pip.

This installs:

- `~/.local/bin/tailscale-gui`
- `~/.local/share/applications/tailscale-gui.desktop`
- `~/.local/share/icons/hicolor/scalable/apps/tailscale-gui.svg`

After this, you can search for **Tailscale GUI** in your app menu and pin it to your panel/dock/applet.

To start directly in tray (applet-style) on login:

```bash
chmod +x install-applet-autostart.sh
./install-applet-autostart.sh
```

You can also launch tray mode manually:

```bash
tailscale-gui --tray
```

## Build .deb Package

```bash
chmod +x packaging/deb/build-deb.sh
./packaging/deb/build-deb.sh 0.1.0 amd64
```

Output:

- `dist/tailscale-gui_0.1.0_amd64.deb`

Install it:

```bash
sudo apt install ./dist/tailscale-gui_0.1.0_amd64.deb
```

The .deb includes tray support. For full functionality, also install the recommended packages:

```bash
sudo apt install python3-pil python3-pystray python3-gi gir1.2-ayatanaappindicator3-0.1
```

Then launch it: `tailscale-gui` or `tailscale-gui --tray`

## Build AppImage

```bash
chmod +x packaging/appimage/build-appimage.sh
./packaging/appimage/build-appimage.sh 0.1.0
```

Output:

- `dist/TailscaleGUI-0.1.0-x86_64.AppImage`

Run it:

```bash
chmod +x dist/TailscaleGUI-0.1.0-x86_64.AppImage
./dist/TailscaleGUI-0.1.0-x86_64.AppImage
```

Note: This AppImage expects `python3`, `python3-tk`, and `tailscale` to exist on the host system.
For tray support in AppImage mode, host Python also needs `pystray` and `Pillow`.

## Tray Behavior

- Closing the window minimizes the app to tray when tray support is available.
- On most Linux desktops, right-click the tray icon to open the quick menu.
- Hover only shows the title; to use actions, open the tray menu.
- If supported by your desktop, left-click triggers the default item: **Open Tailscale GUI**.
- Use tray menu to quickly:
	- Connect (`tailscale up`)
	- Disconnect (`tailscale down`)
	- Refresh status
	- Pick an exit node directly
	- Quit the app fully

## Notes

- This app executes the same CLI commands you would use in terminal.
- If a command requires elevated permissions, you need to run with proper privileges.
- For full CLI coverage, use the **Advanced** tab and type any arguments that normally follow `tailscale`.

## Examples for Advanced tab

- `status`
- `status --json`
- `set --accept-routes=true`
- `set --ssh=true`
- `ping 100.64.0.1`
- `ip`
