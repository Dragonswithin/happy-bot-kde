/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

import org.kde.kcmutils as KCM
import org.kde.kirigami as Kirigami

/**
 * "AI Model" page of the applet's settings dialog (contents/config/config.qml):
 * the user's AIs in the order they are asked, each with its own settings,
 * and the ways to add one (SetupModels.qml), then talking to Happy Bot: the
 * microphone and the speech-to-text service (SetupVoice.qml).
 *
 * The settings belong to the daemon, not to Plasma: DaemonSettings.qml loads
 * them, shows the status line and saves each change at once, and is handed
 * to both as their `page`.
 */
KCM.SimpleKCM {
    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        DaemonSettings {
            id: store
            Layout.fillWidth: true
        }

        SetupModels {
            Layout.fillWidth: true
            visible: store.ready
            page: store
        }

        SetupVoice {
            Layout.fillWidth: true
            visible: store.ready
            page: store
        }
    }
}
