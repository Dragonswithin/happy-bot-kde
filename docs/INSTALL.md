# Install and set up Happy Bot

## Install for your account

Open a terminal in your **KDE Plasma 6 Wayland session**. You’ll need Git to get the source, Python 3.11 or newer, `kpackagetool6`, and a running systemd user session. For window control and typing into applications, install PyGObject (`python-gobject` on Arch or `python3-gi` on Debian) and the AT-SPI accessibility bindings for your distribution.

```sh
git clone https://github.com/Dragonswithin/happy-bot-kde.git
cd happy-bot-kde
scripts/install.sh
```

Run the installer as your regular user. It installs the panel widget, the **Happy Bot** application menu entry, the KRunner integration, shortcuts and command-line tools. It starts the background service for your Plasma session.

On the first install, the script looks for the panel holding your launcher and adds the widget there. If it cannot place the widget, right-click your panel, choose **Add Widgets…**, and drag **Happy Bot** onto the panel. Use `scripts/install.sh --no-panel` if you only want the floating app. You can preview an installation with `--dry-run` or skip enabling and starting the service with `--no-start`.

## First setup

Right-click the Happy Bot icon in your panel and choose **Configure Happy Bot…**. You can also open **Happy Bot** from the application menu and reach settings from its floating shortcut.

1. Under **AI Model**, choose **Find on this computer** for a running local model service, **Online service…** for a listed provider, or **By hand…** to enter a compatible service address and model ID. Choose a model that supports tool calls for desktop actions. Happy Bot tests the connection when you add the model.
2. Under **Search & Tools**, choose **Set up** beside **File search** or **Web search**. Pick a source and click **Use this**. Happy Bot tries a search before saving your choice. File sources can include an existing KDE or plocate index. For tools you already use with another assistant, choose **Find installed tools…** under **Connected tools**.
3. Under **Search & Tools → Setup check**, click **Check everything** to test your AI, search tools and desktop connections.

The panel starts with an icon. To type searches directly into a horizontal panel, select **Appearance → Panel widget → Search bar**. Vertical panels show the icon.

Some features use extra software. Screenshot capture uses Spectacle, marking or cropping a help screenshot uses Python Pillow, and reading its text uses Tesseract with English language data. Event sounds play through `pw-play`, `paplay` or `aplay`. The [Arch package recipe](../packaging/arch/PKGBUILD) lists more feature-specific dependencies.

## Command-line setup

You can also set up models and search tools through `happy-bot`. In the examples below, replace `NAME` with a name for your model, `URL` with your service address, and `ID` with the model ID your service offers.

```sh
happy-bot model probe URL
happy-bot model add NAME --url URL --model ID
happy-bot model test NAME
happy-bot model use NAME
```

For a service that requires an API key, add `--key-stdin` to the probe or add command and provide the key on standard input. For a required extra HTTP header, the add command takes `--header NAME=VALUE`. To test a configured model’s compatibility with Happy Bot, run `happy-bot model check NAME`. This sends a few small requests to that model.

To connect an existing MCP search tool, run `discover` to see available servers, import one by name, then use the names from `list` to assign a role. Repeat for each search source you want to use.

```sh
happy-bot tools discover
happy-bot tools import SERVER
happy-bot tools list
happy-bot role set file_search SERVER TOOL
happy-bot search meeting notes
```

Use `web_search` for the web role. If the search tool takes its query under a particular argument name, add `--query-argument ARGUMENT` to `role set`. Run `happy-bot --help` for other commands and `happy-bot folders` to check the standard folder locations.

## If something doesn’t work

- **A model or search tool fails.** Run `happy-bot doctor` from your Plasma session for checks and fixes. If your shell cannot find the command, use `~/.local/bin/happy-bot doctor` and add `~/.local/bin` to your login session’s `PATH`.
- **Happy Bot cannot reach the background service.** Run `systemctl --user status happy-bot-daemon.service`. If you installed with `--no-start`, run `systemctl --user enable --now happy-bot-daemon.service` from your Plasma session.
- **The widget fails to open.** Run `QT_FORCE_STDERR_LOGGING=1 plasmawindowed io.github.dragonswithin.happybot` to open the installed widget in a window and see QML errors in the terminal.

## Update or uninstall

To update a Git installation, run the following from the checkout. The installer restarts the background service and any running floating app. Log out and back in to load the updated panel widget.

```sh
git pull --ff-only
scripts/install.sh
```

To uninstall, run `scripts/install.sh --uninstall` from the checkout. This removes the installed software, panel widgets and Happy Bot’s reminder and routine timers. If you enabled monthly offline Wikipedia updates, first turn off **Search & Tools → Offline Wikipedia → Check for updates each month** to remove that timer.

The uninstaller keeps settings by default. Add `--purge` to remove the settings directory, including stored API keys. Saved conversations and downloaded Wikipedia archives are stored separately and survive either command. To erase conversations before uninstalling, use **History & Folders → Saved conversations → Clear…**.

### Default locations for a user install

| Contents | Location |
| --- | --- |
| Commands and Python package | `~/.local/bin/` and `~/.local/lib/happy-bot/` |
| Settings and credentials | `~/.config/happy-bot/config.json` (mode 0600) |
| Saved conversations | `~/.local/share/happy-bot/conversations/` |
| Service unit | `~/.config/systemd/user/happy-bot-daemon.service` |
| Widget | `~/.local/share/plasma/plasmoids/io.github.dragonswithin.happybot/` |
| Session files and service access token | `$XDG_RUNTIME_DIR/happy-bot/` |

The settings and data directories follow `XDG_CONFIG_HOME` and `XDG_DATA_HOME` when set. The service only accepts loopback connections. The widget and CLI read its private token automatically.

## Arch package

To install system-wide on Arch Linux, run `makepkg -si` from [packaging/arch](../packaging/arch) in a checkout. Each user then runs `systemctl --user enable --now happy-bot-daemon.service` in their Plasma session and adds **Happy Bot** from **Add Widgets…**. The service and settings still belong to each individual user. Manage this installation with pacman.
