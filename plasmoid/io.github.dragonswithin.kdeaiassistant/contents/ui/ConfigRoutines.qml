/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

import org.kde.kcmutils as KCM
import org.kde.kirigami as Kirigami

/**
 * "Routines & Reminders" page of the applet's settings dialog
 * (contents/config/config.qml): the user's saved routines and the reminders
 * that are set.
 *
 * The settings belong to the daemon, not to Plasma: DaemonSettings.qml loads
 * them, shows the status line and saves each change at once, and is handed
 * to SetupRoutines.qml as their `page`.
 */
KCM.SimpleKCM {
    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        DaemonSettings {
            id: store
            Layout.fillWidth: true
        }

        SetupRoutines {
            id: routinesSection
            Layout.fillWidth: true
            visible: store.ready
            page: store
        }
    }
}
