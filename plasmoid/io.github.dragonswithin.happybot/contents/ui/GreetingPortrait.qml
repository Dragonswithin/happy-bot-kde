// SPDX-License-Identifier: MIT
// The start screen and Appearance share the same portrait and one-shot greeting.
pragma ComponentBehavior: Bound
import QtQuick
import org.kde.kirigami as Kirigami

Item {
    id: portrait
    required property string iconSource
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
        Kirigami.Icon {
            id: face
            anchors.centerIn: parent
            width: parent.width * 0.58
            height: width
            source: portrait.iconSource
            transformOrigin: Item.Bottom

            SequentialAnimation on rotation {
                running: portrait.animate && portrait.visible && portrait.Window.window !== null
                         && portrait.Window.window.visible && Kirigami.Units.longDuration > 1
                NumberAnimation { from: 0; to: -12; duration: Kirigami.Units.longDuration; easing.type: Easing.OutSine }
                NumberAnimation { to: 5; duration: Kirigami.Units.shortDuration; easing.type: Easing.InOutSine }
                NumberAnimation { to: 0; duration: Kirigami.Units.longDuration; easing.type: Easing.OutCubic }
                onStopped: face.rotation = 0
            }
        }
    }
}
