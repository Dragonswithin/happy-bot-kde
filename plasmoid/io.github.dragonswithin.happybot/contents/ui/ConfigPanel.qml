/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kcmutils as KCM
import org.kde.kirigami as Kirigami

/**
 * "Panel" page of the panel widget's settings dialog: only what concerns
 * this widget in the panel. Everything else is Happy Bot's own and lives
 * in the app (ConfigAppearance.qml and the daemon's pages), which the
 * "Open Happy Bot settings" button opens, starting the app if needed
 * (`POST /app`, `POST /app/show` with "settings", src/happy_bot/app_control.py).
 *
 * Settings here are this widget's own Plasma settings (contents/config/main.xml),
 * bound through `cfg_<name>` and written when the user applies: what the
 * panel shows (`inputInPanel`: the icon, or a search bar), the bar's width
 * (`barWidth`, grid units 8 to 60) and, for unusual setups, the daemon's
 * address (`daemonUrl`). The page keeps no other state.
 */
KCM.SimpleKCM {
    id: page

    property bool cfg_inputInPanel
    property alias cfg_barWidth: barWidth.value
    property alias cfg_daemonUrl: daemonUrl.text

    DaemonClient {
        id: client
        configuredUrl: page.cfg_daemonUrl || ""
    }

    Kirigami.FormLayout {
        QQC2.RadioButton {
            Kirigami.FormData.label: i18n("Show in panel:")
            text: i18n("Icon that opens Happy Bot")
            checked: !page.cfg_inputInPanel
            onToggled: if (checked) page.cfg_inputInPanel = false
        }

        QQC2.RadioButton {
            text: i18n("Search bar")
            checked: page.cfg_inputInPanel
            onToggled: if (checked) page.cfg_inputInPanel = true
        }

        QQC2.SpinBox {
            id: barWidth
            Kirigami.FormData.label: i18n("Search bar width:")
            enabled: page.cfg_inputInPanel
            from: 8
            to: 60
        }

        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            wrapMode: Text.Wrap
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            text: i18n("While you type in the search bar, Plasma outlines the panel in its focus colour; the icon avoids that. Vertical panels always show the icon.")
        }

        Item {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18n("Happy Bot")
        }

        QQC2.Button {
            text: i18n("Open Happy Bot settings…")
            icon.name: "configure"
            highlighted: true
            onClicked: client.request("POST", "/app", { start: true }, function(data) {
                client.request("POST", "/app/show", { action: "settings" }, function(data) {}, function(data) {});
            }, function(data) {})
        }

        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            wrapMode: Text.Wrap
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            text: i18n("AI models, search, behaviour, history, routines and Happy Bot's look (the mascot, the popup, the floating Happy Bot) are set in Happy Bot itself, so this panel widget and the floating Happy Bot always match.")
        }

        Item {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: i18n("Advanced")
        }

        QQC2.TextField {
            id: daemonUrl
            Kirigami.FormData.label: i18n("Assistant address:")
            Layout.minimumWidth: Kirigami.Units.gridUnit * 16
            placeholderText: i18n("Automatic")
        }

        QQC2.Label {
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            wrapMode: Text.Wrap
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            text: i18n("Leave empty. Only needed when the assistant's background service was started on a different port.")
        }
    }
}
