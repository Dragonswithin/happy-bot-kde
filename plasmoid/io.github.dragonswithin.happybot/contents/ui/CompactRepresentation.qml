/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick

import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

/**
 * The applet's default panel form: a button showing the selected assistant
 * icon (the other form, chosen with the `inputInPanel` setting, is the
 * search bar in PanelBar.qml). A left click opens or closes the popup
 * (ResultsPopup.qml), where all typing happens in this form; a right click
 * asks for the applet's menu. Both are reported as signals and
 * main.qml decides what they do. The applet's activation shortcut does the
 * same as a left click.
 *
 * The icon also shows the assistant's state with a small corner badge (see
 * below) and a highlighted background while the popup is open. It holds no
 * state of its own.
 */
Item {
    id: compact

    property string status: "idle"
    property string iconName: "tools-wizard"
    property alias activity: icon.activity
    property alias animateMascot: icon.animateMascot
    property alias robotStyle: icon.robotStyle
    property color accent: Kirigami.Theme.highlightColor
    property bool busy: false
    property bool needsAttention: false
    property bool open: false

    signal clicked()
    signal menuRequested()

    implicitWidth: Kirigami.Units.iconSizes.medium
    implicitHeight: Kirigami.Units.iconSizes.medium

    Accessible.role: Accessible.Button
    Accessible.name: i18n("Open Happy Bot")

    Rectangle {
        anchors.fill: parent
        anchors.margins: -Kirigami.Units.smallSpacing / 2
        radius: Kirigami.Units.cornerRadius
        color: Qt.alpha(Kirigami.Theme.textColor, compact.open || mouse.pressed ? 0.16 : mouse.containsMouse ? 0.08 : 0)

        Behavior on color {
            ColorAnimation {
                duration: Kirigami.Units.shortDuration
            }
        }
    }

    PanelIcon {
        id: icon
        anchors.fill: parent
        iconName: compact.iconName
        hovered: mouse.containsMouse
        opacity: compact.status === "offline" ? 0.6 : 1.0
    }

    // Status badge in the bottom-right corner, the way Plasma's tray icons
    // show state: attention colour with "!" while an action waits for
    // approval, a breathing highlight dot while a request runs, and a grey
    // dot when the daemon cannot be reached.
    Rectangle {
        id: badge

        readonly property string kind: compact.needsAttention ? "attention"
            : compact.busy ? "busy"
            : compact.status === "offline" ? "offline" : ""

        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: -Kirigami.Units.smallSpacing / 2
        width: Math.round(parent.width * 0.46)
        height: width
        radius: width / 2
        visible: kind.length > 0
        color: kind === "attention" ? Kirigami.Theme.neutralTextColor
            : kind === "busy" ? compact.accent
            : Kirigami.Theme.disabledTextColor
        border.width: 1
        border.color: Kirigami.Theme.backgroundColor

        PlasmaComponents3.Label {
            anchors.centerIn: parent
            visible: badge.kind === "attention"
            text: "!"
            font.bold: true
            font.pixelSize: badge.height * 0.8
            color: Kirigami.Theme.backgroundColor
        }

        SequentialAnimation on opacity {
            running: badge.kind === "busy" || badge.kind === "attention"
            loops: Animation.Infinite
            onRunningChanged: if (!running) badge.opacity = 1
            NumberAnimation { from: 1; to: 0.35; duration: 800; easing.type: Easing.InOutSine }
            NumberAnimation { from: 0.35; to: 1; duration: 800; easing.type: Easing.InOutSine }
        }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: event => {
            if (event.button === Qt.RightButton) {
                compact.menuRequested();
            } else {
                compact.clicked();
            }
        }
    }
}
