// SPDX-License-Identifier: MIT
// One current desktop condition and its suggested next request, shown inside the open assistant.
pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

Rectangle {
    id: card
    required property string kind
    required property bool needsSetup
    required property color accent
    property string problem: ""
    signal chosen(string message)
    signal setupRequested()
    signal dismissRequested(string kind)

    readonly property var suggestion: {
        switch (kind) {
        case "battery":
            return { icon: "battery-low",
                     action: i18n("Use power saver"), prompt: i18n("Switch this computer to its power saver profile.") };
        case "disk":
            return { icon: "drive-harddisk",
                     action: i18n("Find what’s taking space"), prompt: i18n("Find which disk is low on space and show me what’s taking up room on it. Leave my files in place.") };
        case "restart":
            return { icon: "system-reboot",
                     action: i18n("Restart…"), prompt: i18n("Help me restart this computer. Ask for my approval before restarting.") };
        case "updates":
            return { icon: "system-software-update",
                     action: i18n("Review updates"), prompt: i18n("Show me which software updates are waiting so I can decide what to install.") };
        default: return null;
        }
    }
    onKindChanged: problem = ""
    implicitHeight: column.implicitHeight + 2 * Kirigami.Units.smallSpacing
    color: Qt.alpha(accent, 0.08)

    ColumnLayout {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.margins: Kirigami.Units.largeSpacing
        spacing: 0
        RowLayout {
            Layout.fillWidth: true
            Kirigami.Icon {
                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                Layout.preferredHeight: Layout.preferredWidth
                source: card.suggestion?.icon || ""
                Accessible.ignored: true
            }
            PlasmaComponents3.Label {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                wrapMode: Text.Wrap
                text: Look.nudgeTitle(card.kind)
                font.weight: Font.DemiBold
            }
            PlasmaComponents3.Button {
                text: card.needsSetup ? i18n("Set up an AI…") : card.suggestion?.action || ""
                onClicked: card.needsSetup ? card.setupRequested() : card.chosen(card.suggestion.prompt)
            }
            PlasmaComponents3.ToolButton {
                text: i18n("Dismiss this nudge")
                icon.name: "dialog-close"
                display: QQC2.AbstractButton.IconOnly
                AssistantToolTip {
                    accent: card.accent
                    text: parent.text
                    visible: parent.hovered || parent.visualFocus
                }
                onClicked: card.dismissRequested(card.kind)
            }
        }
        PlasmaComponents3.Label {
            Layout.fillWidth: true
            visible: card.problem.length > 0
            text: card.problem
            wrapMode: Text.Wrap
            color: Kirigami.Theme.negativeTextColor
        }
    }
}
