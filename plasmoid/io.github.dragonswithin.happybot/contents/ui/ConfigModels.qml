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
 * which model answers and everything stored about it.
 *
 * The settings belong to the daemon, not to Plasma: DaemonSettings.qml loads
 * them, shows the status line and saves each change at once, and is handed
 * to SetupModels.qml and ModelDetails.qml as their `page`. The sections are
 * Kirigami.FormLayouts linked with `twinFormLayouts`, so their labels share
 * one column like a System Settings page.
 */
KCM.SimpleKCM {
    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        DaemonSettings {
            id: store
            Layout.fillWidth: true
        }

        SetupModels {
            id: modelsSection
            Layout.fillWidth: true
            visible: store.ready
            page: store
            twinFormLayouts: [detailsSection]
        }

        ModelDetails {
            id: detailsSection
            Layout.fillWidth: true
            visible: store.ready
            page: store
            twinFormLayouts: [modelsSection]
        }
    }
}
