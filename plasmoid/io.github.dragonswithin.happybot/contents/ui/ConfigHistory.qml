/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

import org.kde.kcmutils as KCM
import org.kde.kirigami as Kirigami

/**
 * "History & Folders" page of the applet's settings dialog (contents/config/config.qml):
 * clear Happy Bot’s history and temporary data, set conversation retention,
 * and choose the standard folders and files for notes and to-dos.
 *
 * The settings belong to the daemon, not to Plasma: DaemonSettings.qml loads
 * them, shows the status line and saves each change at once, and is handed
 * to SetupHistory.qml as their `page`.
 */
KCM.SimpleKCM {
    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        DaemonSettings {
            id: store
            Layout.fillWidth: true
        }

        SetupHistory {
            id: historySection
            Layout.fillWidth: true
            visible: store.ready
            page: store
        }
    }
}
