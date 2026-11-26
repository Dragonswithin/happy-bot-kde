// SPDX-License-Identifier: MIT
// Animate the eyes on the original 48-unit mascot.
pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Shapes
import org.kde.kirigami as Kirigami

Item {
    id: robot
    property bool animate: true
    property string expressionSource: ""
    readonly property bool canMove: animate && visible && width > 0 && height > 0
        && Window.window !== null && Window.window.visible && Window.window.visibility !== Window.Minimized
        && Kirigami.Units.longDuration > 1
    readonly property real unit: Math.min(width, height) / 48
    Accessible.ignored: true

    function duration(ms: real): int {
        // Give the eyes time to move even when Plasma's UI transitions are fast.
        return Math.round(ms * Math.max(1, Kirigami.Units.longDuration / 200));
    }

    QtObject {
        id: pose
        objectName: "characterPose"
        property real eyelid: 1
        property real gaze: 0
    }

    component Beat: NumberAnimation {
        target: pose
        required property int ms
        duration: robot.duration(ms)
        easing.type: Easing.InOutSine
    }

    SequentialAnimation {
        running: robot.canMove && !robot.expressionSource
        loops: Animation.Infinite
        PauseAnimation { duration: 2800 }
        Beat { property: "eyelid"; to: 0.12; ms: 90 }
        Beat { property: "eyelid"; to: 1; ms: 145 }
        PauseAnimation { duration: 1300 }
        Beat { property: "gaze"; to: 2.6; ms: 420 }
        PauseAnimation { duration: robot.duration(880) }
        Beat { property: "gaze"; to: -2.4; ms: 760 }
        PauseAnimation { duration: robot.duration(800) }
        Beat { property: "eyelid"; to: 0.12; ms: 100 }
        Beat { property: "eyelid"; to: 1; ms: 145 }
        Beat { property: "gaze"; to: 0; ms: 440 }
        onStopped: { pose.eyelid = 1; pose.gaze = 0; }
    }

    Image {
        anchors.fill: parent
        fillMode: Image.PreserveAspectFit
        source: robot.canMove ? "../images/character/shell.svg" : Look.robotIcon
        sourceSize.width: Math.ceil(robot.unit * 48)
    }

    Item {
        anchors.centerIn: parent
        width: 48
        height: 48
        scale: robot.unit
        visible: robot.canMove

        component Eye: Shape {
            width: 9; height: 10
            y: 20
            transform: Scale { origin.y: 5; yScale: pose.eyelid }
            ShapePath {
                fillColor: "transparent"
                strokeColor: "#adfff1"
                strokeWidth: 4
                capStyle: ShapePath.RoundCap
                startX: 4; startY: 4
                PathLine { x: 4; y: 6 }
            }
        }

        Eye { x: 13 + pose.gaze }
        Eye { x: 27 + pose.gaze }
    }

    Image {
        anchors.fill: parent
        fillMode: Image.PreserveAspectFit
        source: robot.expressionSource
        sourceSize.width: Math.ceil(robot.unit * 48)
    }
}
