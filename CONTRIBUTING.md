# Contributing to Happy Bot

This page covers how to report a problem, suggest an idea, or send a change
to Happy Bot. Happy Bot is a hobby project maintained by one person, so
replies may take a few days.

## Reporting a Problem

Open an issue with **Something went wrong**
(<https://github.com/Dragonswithin/happy-bot-kde/issues/new/choose>), or
choose **Send feedback…** from Happy Bot's right-click menu, which opens the
same page. The form asks for your Plasma version, how you installed Happy
Bot, which kind of AI answered, and the output of:

```bash
happy-bot doctor
```

That check is short and contains no API keys. Please don't paste
conversations or `~/.config/happy-bot/config.json`: they can contain
whatever the assistant read for you.

## Ideas and Impressions

- A specific thing you wish it did: **Idea or request**. Write it the way
  you would type it into the bar. That matters more than a feature name.
- Anything else ("I tried it with model X and…", "this confused me",
  screenshots of your setup): post in
  [Discussions](https://github.com/Dragonswithin/happy-bot-kde/discussions).
  Hearing which models and search tools people use helps most.

## Sending a Change

1. Read `docs/ROADMAP.md` first. It sets the product goal (one bar, any AI,
   your existing tools through MCP, one app) and the phase order.
   `docs/FEATURES.md` is the backlog. For anything bigger than a fix,
   open an issue first so we can agree on the shape.
2. Code must not assume any model, vendor or endpoint. Local services
   may be offered as suggestions, but the user chooses.
3. Anything that deletes or changes the system must go through the
   approval flow. Root actions belong to an external broker, never to
   Happy Bot itself.
4. Run the checks in the README's **Checks** section, at least:

   ```bash
   python3 -m unittest discover -s tests
   QT_FORCE_STDERR_LOGGING=1 /usr/lib/qt6/bin/qmllint -I /usr/lib/qt6/qml plasmoid/*/contents/ui/*.qml
   ```

5. Every new source file starts with a header comment that says what it is
   responsible for. Follow the existing files.

By contributing you agree that your change is released under the project's
MIT license (`LICENSE`).
