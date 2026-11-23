/*
    SPDX-License-Identifier: MIT
*/

import QtQuick

import org.kde.plasma.configuration

/**
 * Pages shown in the applet's "Configure…" dialog. "Assistant" comes first
 * because it is where setup happens: models, search tools, approvals and
 * folders, all stored by the daemon. "Appearance" holds the applet's own
 * Plasma settings declared in main.xml. Plasma adds its Keyboard Shortcuts
 * page, where the user sets the shortcut that focuses the bar.
 */
ConfigModel {
    ConfigCategory {
        name: i18n("Assistant")
        icon: "assistant"
        source: "ConfigSetup.qml"
    }
    ConfigCategory {
        name: i18n("Appearance")
        icon: "preferences-desktop-theme"
        source: "ConfigGeneral.qml"
    }
}
