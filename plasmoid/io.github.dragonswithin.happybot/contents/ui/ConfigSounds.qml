// SPDX-License-Identifier: MIT
pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kcmutils as KCM
import org.kde.kirigami as Kirigami

KCM.SimpleKCM {
    id: page
    property string cfg_daemonUrl: ""
    property string problem: ""

    Connections {
        target: SharedUiPreferences
        function onProblem(message) { page.problem = message; }
    }
    Component.onCompleted: {
        SharedUiPreferences.configuredUrl = cfg_daemonUrl || "";
        SharedUiPreferences.read();
    }

    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing
        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: page.problem.length > 0
            text: page.problem
            type: Kirigami.MessageType.Error
            actions: [Kirigami.Action {
                text: i18n("Try again")
                visible: !SharedUiPreferences.ui
                onTriggered: {
                    page.problem = "";
                    SharedUiPreferences.read();
                }
            }]
        }
        EventSounds {
            Layout.fillWidth: true
            enabled: SharedUiPreferences.ui !== null
            choices: SharedUiPreferences.ui?.event_sounds ?? ({})
            onEdited: (event, fields) => SharedUiPreferences.save({event_sounds: { [event]: fields }})
            onPreviewRequested: (event, theme) => SharedUiPreferences.preview(event, theme)
        }
    }
}
