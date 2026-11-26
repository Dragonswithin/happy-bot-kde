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

1. Read the [roadmap](docs/ROADMAP.md) first. It sets the product goal (one bar, any AI,
   your existing tools through MCP, one app) and the phase order.
   The [feature backlog](docs/FEATURES.md) tracks individual requests. For anything bigger than a fix,
   open an issue first so we can agree on the shape.
2. Code must not assume any model, vendor or endpoint. Local services
   may be offered as suggestions, but the user chooses.
3. Route the assistant's tool calls through the permission gate. Deletions
   and OS-level changes need approval each time. Root actions belong to an
   external broker.
4. Run the [checks](#checks) from the checkout.
5. Every new source file starts with a header comment that says what it is
   responsible for. Follow the existing files.

By contributing you agree that your change is released under the project's
MIT license ([LICENSE](LICENSE)).

## Checks

Run the Python tests and check the shell and QML sources. The examples use
the Qt 6 tool paths on Arch Linux.

```bash
python3 -m unittest discover -s tests
python3 -m compileall -q src/happy_bot
printf '%s\0' scripts/*.sh launchers/happy-bot-app | xargs -0 -n1 bash -n
QT_FORCE_STDERR_LOGGING=1 /usr/lib/qt6/bin/qmllint -I /usr/lib/qt6/qml plasmoid/*/contents/ui/*.qml
/usr/lib/qt6/bin/qmltestrunner -input tests
systemd-analyze --user verify systemd/user/happy-bot-daemon.service
```

For a live check after installing, run `happy-bot doctor` and open the
widget in its own window. To see load errors in the terminal, use
`QT_FORCE_STDERR_LOGGING=1 plasmawindowed io.github.dragonswithin.happybot`.

## Trying a change locally

To try this checkout with empty settings, start a second daemon and use
its environment in a subshell. The final command removes its temporary
settings and history. Tools connected to this daemon can still act on your
desktop.

```bash
scripts/throwaway_daemon.sh start
(
    eval "$(scripts/throwaway_daemon.sh env)"
    python3 -m happy_bot.cli doctor
)
scripts/throwaway_daemon.sh stop
```

The daemon authenticates local clients using a per-start token in
`$XDG_RUNTIME_DIR/happy-bot/token` (mode 0600). It checks the HTTP Host
and rejects requests with an Origin header. The CLI and widget read the
token themselves.

- **Preview a view.** For a self-contained QML component, run
  `scripts/preview_qml.sh AnswerBody.qml "$XDG_RUNTIME_DIR/happy-bot/answer.png" 'text: "Hello"'`.
- **Check model compatibility.** `happy-bot model check --all` sends small
  requests to your configured models. The Python tests also replay saved
  responses offline. To preview a fixture recording, run
  `scripts/record_model_replies.py LABEL=MODEL`. Add `--record` to make the
  requests and save the replies.
- **Translate the widget.** Run `scripts/translations.sh template` to
  generate the gettext template. Translations go in `po/<language>.po`.
  Run `scripts/translations.sh merge` to refresh them after a string
  changes. Both installers compile the translations.
