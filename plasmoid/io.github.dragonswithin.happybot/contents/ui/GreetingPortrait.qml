// SPDX-License-Identifier: MIT
// The start screen and Appearance share the same mascot portrait.
pragma ComponentBehavior: Bound
import QtQuick
import org.kde.kirigami as Kirigami

Item {
    id: portrait
    required property string iconSource
    property string robotStyle: "pip"
    property bool animate: false
    property color accent: Look.mascotAccent
    implicitWidth: Kirigami.Units.gridUnit * 4
    implicitHeight: implicitWidth
    Accessible.ignored: true

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(parent.width, parent.height)
        height: width
        radius: width / 2
        color: "transparent"
        border.color: Qt.alpha(portrait.accent, 0.25)

        Rectangle {
            anchors.centerIn: parent
            width: parent.width * 0.76
            height: width
            radius: width / 2
            color: Qt.alpha(portrait.accent, 0.10)
            border.color: Qt.alpha(portrait.accent, 0.19)
        }
        Rectangle {
            x: parent.width * 0.15 - width / 2
            y: parent.height * 0.145 - height / 2
            width: Kirigami.Units.smallSpacing * 1.6
            height: width
            radius: width / 2
            color: portrait.accent
        }
        RobotCharacter {
            id: character
            anchors.centerIn: parent
            width: parent.width * 0.8
            height: width
            visible: portrait.iconSource === Look.robotImage(portrait.robotStyle).toString()
            robotStyle: portrait.robotStyle
            animate: portrait.animate
        }
        Kirigami.Icon {
            anchors.centerIn: parent
            width: parent.width * 0.58
            height: width
            visible: !character.visible
            source: visible ? portrait.iconSource : ""
        }
    }
}
