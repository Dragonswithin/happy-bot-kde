#!/bin/sh
# Extracts the applet's translatable strings (every i18n/i18np call in the QML
# and JavaScript) into the translation template that translators start from,
# in the KDE convention: the scripty tooling sets $XGETTEXT and $podir. Run
# by hand with, for example:
#   XGETTEXT="xgettext --from-code=UTF-8 -C -ki18n -ki18np:1,2" podir=/tmp sh Messages.sh
# Plasma loads translations for this applet from the domain
# plasma_applet_io.github.dragonswithin.happybot. The daemon's own messages
# (src/happy_bot) are English only for now. Outside KDE's tooling,
# scripts/translations.sh makes the same template and compiles po/*.po files.
$XGETTEXT $(find . -name '*.qml' -o -name '*.js') -o "$podir/plasma_applet_io.github.dragonswithin.happybot.pot"
