"""KDE AI Assistant: the per-user daemon and CLI behind the Plasma panel bar.

The package is installed as a plain directory (see ``scripts/install.sh``) and
started through the thin launchers in ``launchers/``. ``daemon_http`` is the
long-running process; ``cli`` is the command-line client that talks to it.

``__version__`` must equal the applet's ``KPlugin.Version`` in
``plasmoid/io.github.dragonswithin.kdeaiassistant/metadata.json``; the self-check
compares the two to spot a panel still running an old applet.
"""

__version__ = "0.1.0"
