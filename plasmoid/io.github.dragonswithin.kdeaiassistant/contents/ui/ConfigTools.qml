/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

import org.kde.kcmutils as KCM
import org.kde.kirigami as Kirigami

/**
 * "Search & Tools" page of the applet's settings dialog (contents/config/config.qml):
 * the file and web search tools and the connected tool servers.
 *
 * The settings belong to the daemon, not to Plasma: DaemonSettings.qml loads
 * them, shows the status line and saves each change at once, and is handed
 * to SetupTools.qml as their `page`.
 */
KCM.SimpleKCM {
    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        DaemonSettings {
            id: store
            Layout.fillWidth: true
        }

        SetupTools {
            id: toolsSection
            Layout.fillWidth: true
            visible: store.ready
            page: store
        }
    }
}
