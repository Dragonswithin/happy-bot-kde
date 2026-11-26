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

        SettingsSection {
            id: diagnostics
            appearance: store.settings?.ui
            visible: store.ready
            title: i18n("Setup check")
            iconName: "preferences-system"
            description: i18n("Test your AI, search tools and desktop connections.")

            property bool checking: false
            property string result: ""
            property bool failed: false

            QQC2.Button {
                enabled: !diagnostics.checking
                text: diagnostics.checking ? i18n("Checking…") : i18n("Check everything")
                icon.name: "checkmark"
                onClicked: {
                    diagnostics.checking = true;
                    diagnostics.result = "";
                    store.client.request("GET", "/check", null, function(data) {
                        diagnostics.checking = false;
                        const problems = data.checks.filter(item => !item.ok);
                        diagnostics.failed = problems.length > 0;
                        diagnostics.result = diagnostics.failed
                            ? problems.map(item => item.name + ": " + item.detail + " " + item.fix).join("\n\n")
                            : i18n("Everything works.");
                    }, function(data) {
                        diagnostics.checking = false;
                        diagnostics.failed = true;
                        diagnostics.result = data.error || i18n("The check could not run");
                    });
                }
            }
            Kirigami.InlineMessage {
                Layout.fillWidth: true
                visible: diagnostics.result.length > 0
                text: diagnostics.result
                type: diagnostics.failed ? Kirigami.MessageType.Error : Kirigami.MessageType.Positive
            }
        }
    }
}
