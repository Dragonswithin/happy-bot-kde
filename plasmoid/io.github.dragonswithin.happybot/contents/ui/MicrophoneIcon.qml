/*
    SPDX-License-Identifier: MIT
*/

import QtQuick
import QtQuick.Shapes

Item {
    id: icon
    objectName: "themedMicrophone"
    required property color accent
    property bool recording: false
    readonly property color outline: Qt.tint("#183840", Qt.alpha(accent, 0.16))
    Accessible.ignored: true

    Shape {
        anchors.centerIn: parent
        width: 32
        height: 32
        scale: Math.min(icon.width, icon.height) / 32

        ShapePath {
            fillColor: "transparent"
            strokeColor: icon.outline
            strokeWidth: 4.8
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathSvg { path: "M7 14.5a9 9 0 0 0 18 0M16 23.5v3.5m-5 0h10" }
        }
        ShapePath {
            fillColor: "transparent"
            strokeColor: icon.accent
            strokeWidth: 2.6
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathSvg { path: "M7 14.5a9 9 0 0 0 18 0M16 23.5v3.5m-5 0h10" }
        }
        ShapePath {
            fillColor: icon.accent
            strokeColor: icon.outline
            strokeWidth: 2
            PathSvg { path: "M16 4a6 6 0 0 1 6 6v4.5a6 6 0 0 1-12 0v-4.5a6 6 0 0 1 6-6Z" }
        }
        ShapePath {
            fillColor: icon.recording ? "#ff696b" : "transparent"
            strokeColor: icon.outline
            strokeWidth: icon.recording ? 1.2 : 2
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathSvg { path: icon.recording ? "M13 9h6v6h-6Z" : "M13.5 10h5m-5 4h5" }
        }
    }
}
