/*
    SPDX-License-Identifier: MIT
*/

import QtQuick

import org.kde.plasma.configuration

/**
 * Pages shown in the applet's "Configure…" dialog. Plasma adds its own
 * Keyboard Shortcuts page, where the user sets the shortcut that focuses the
 * bar. The settings themselves are declared in main.xml.
 */
ConfigModel {
    ConfigCategory {
        name: i18n("General")
        icon: "configure"
        source: "ConfigGeneral.qml"
    }
}
