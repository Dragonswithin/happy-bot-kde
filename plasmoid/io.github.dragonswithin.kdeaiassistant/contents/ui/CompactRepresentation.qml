/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2

import org.kde.kirigami as Kirigami
import org.kde.plasma.plasmoid

Item {
    id: root

    required property PlasmoidItem plasmoidItem
    property string status: "idle"

    implicitWidth: Kirigami.Units.iconSizes.medium
    implicitHeight: Kirigami.Units.iconSizes.medium

    MouseArea {
        anchors.fill: parent
        onClicked: root.plasmoidItem.expanded = !root.plasmoidItem.expanded
    }

    Kirigami.Icon {
        id: icon
        anchors.fill: parent
        source: Plasmoid.icon
        opacity: root.status === "offline" ? 0.45 : 1.0
    }

    QQC2.BusyIndicator {
        anchors.centerIn: parent
        width: parent.width
        height: parent.height
        running: root.status === "thinking"
        visible: running
    }

    Rectangle {
        width: Kirigami.Units.smallSpacing * 1.8
        height: width
        radius: width / 2
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        color: {
            if (root.status === "thinking") return Kirigami.Theme.activeTextColor;
            if (root.status === "needs_approval") return Kirigami.Theme.neutralTextColor;
            if (root.status === "offline") return Kirigami.Theme.negativeTextColor;
            return Kirigami.Theme.positiveTextColor;
        }
        border.color: Kirigami.Theme.backgroundColor
        border.width: 1
    }
}
