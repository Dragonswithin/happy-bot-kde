# Happy Bot

Happy Bot puts a search bar and a desktop assistant in your KDE Plasma 6 panel.
Type an app name and press Enter to launch it, or find a document through your
existing file index. These searches work without an AI. Choose **Ask Happy Bot
about …** when you want the assistant to answer or act.

Ask “What’s new in KDE this week?” to search the web with your chosen search
tool, or “Put Firefox on the left half of my screen” to arrange a window.
You choose the model, either one running on your computer or a compatible
hosted service. You can also open Happy Bot as a floating desktop button.

![Happy Bot’s start screen above the Plasma panel, with shortcuts for file search, web search, desktop help and system info](docs/images/happy-bot.webp)

## Get started

From a KDE Plasma 6 Wayland session with Python 3.11 or newer, run these
commands as your regular user.

```bash
git clone https://github.com/Dragonswithin/happy-bot-kde.git
cd happy-bot-kde
scripts/install.sh
```

1. Right-click the **Happy Bot** panel icon and choose **Configure Happy Bot…**.
   You can also open **Happy Bot** from the application menu and right-click its floating button.
2. Under **AI Model**, choose **Find on this computer** or **Online service…**.
   Under **Search & Tools**, choose **Set up** next to **File search** or **Web search**.
3. To type directly into a horizontal panel, select **Appearance → Panel widget → Search bar**.

For dependencies, updates and removal, see the [installation guide](docs/INSTALL.md).

## Privacy and control

With a hosted model, your request and the tool results it uses can reach that
service, including file contents or clipboard text. By default, only local
models receive context captured by **Help with…**. The assistant asks before
deleting files or installing software. You can require approval for more
actions under **Behaviour**.

## Explore the project

- [User guide](docs/USAGE.md) – panel shortcuts, web search, app help and settings.
- [Roadmap](docs/ROADMAP.md) and [feature backlog](docs/FEATURES.md) – project goals and ongoing work.
- [Report a problem](https://github.com/Dragonswithin/happy-bot-kde/issues/new/choose), [join a discussion](https://github.com/Dragonswithin/happy-bot-kde/discussions) or [contribute a change](CONTRIBUTING.md).
