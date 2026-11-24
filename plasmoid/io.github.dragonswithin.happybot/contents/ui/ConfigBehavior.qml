/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

import org.kde.kcmutils as KCM
import org.kde.kirigami as Kirigami

/**
 * "Behaviour" page of the applet's settings dialog (contents/config/config.qml):
 * approvals, what the assistant may do, the user's own instructions, limits and the terminal.
 *
 * The settings belong to the daemon, not to Plasma: DaemonSettings.qml loads
 * them, shows the status line and saves each change at once, and is handed
 * to SetupBehavior.qml as their `page`.
 */
KCM.SimpleKCM {
    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        DaemonSettings {
            id: store
            Layout.fillWidth: true
        }

        SetupBehavior {
            id: behaviorSection
            Layout.fillWidth: true
            visible: store.ready
            page: store
        }
    }
}
