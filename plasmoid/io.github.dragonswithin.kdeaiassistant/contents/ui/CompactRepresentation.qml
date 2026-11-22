/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2

import org.kde.kirigami as Kirigami

/**
 * Icon form of the applet, used where an inline text field cannot work: a
 * vertical panel, or when the user enables "type in the popup" because the
 * panel field does not receive keyboard focus on their system.
 *
 * It shows the daemon status as a coloured dot and a busy spinner, and emits
 * `clicked`; main.qml opens the results popup with its own input field in
 * response. It holds no state of its own.
 */
Item {
    id: compact

    property string status: "idle"
    property string iconName: "search"

    signal clicked()

    implicitWidth: Kirigami.Units.iconSizes.medium
    implicitHeight: Kirigami.Units.iconSizes.medium

    MouseArea {
        anchors.fill: parent
        onClicked: compact.clicked()
    }

    Kirigami.Icon {
        anchors.fill: parent
        source: compact.iconName
        opacity: compact.status === "offline" ? 0.45 : 1.0
    }

    QQC2.BusyIndicator {
        anchors.fill: parent
        running: compact.status === "thinking"
        visible: running
    }

    Rectangle {
        width: Kirigami.Units.smallSpacing * 1.8
        height: width
        radius: width / 2
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        color: {
            if (compact.status === "thinking") return Kirigami.Theme.activeTextColor;
            if (compact.status === "offline") return Kirigami.Theme.negativeTextColor;
            return Kirigami.Theme.positiveTextColor;
        }
        border.color: Kirigami.Theme.backgroundColor
        border.width: 1
    }
}
