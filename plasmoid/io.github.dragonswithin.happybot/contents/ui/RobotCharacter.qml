// SPDX-License-Identifier: MIT
// The static icon and animated parts come from the same 48-unit drawing.
pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Shapes
import org.kde.kirigami as Kirigami
import org.kde.ksvg as KSvg

Item {
    id: robot
    property bool animate: true
    property string robotStyle: "pip"
    property string expressionSource: ""
    readonly property var design: Look.robotDesign(robotStyle)
    readonly property url artwork: Look.robotImage(design.id)
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
        property real gesture: 0
    }

    component Beat: NumberAnimation {
        target: pose
        required property int ms
        duration: robot.duration(ms)
        easing.type: Easing.InOutSine
    }

    SequentialAnimation {
        id: idle
        running: robot.canMove
        loops: Animation.Infinite
        PauseAnimation { duration: 950 }
        Beat { property: "gesture"; to: 1; ms: robot.design.ms }
        Beat { property: "gesture"; to: 0; ms: robot.design.ms }
        PauseAnimation { duration: 650 }
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
        onStopped: { pose.eyelid = 1; pose.gaze = 0; pose.gesture = 0; }
    }

    // Preview the newly chosen robot from its resting pose.
    onRobotStyleChanged: if (idle.running) idle.restart()

    Image {
        anchors.fill: parent
        fillMode: Image.PreserveAspectFit
        visible: !robot.canMove
        source: robot.artwork
        sourceSize.width: Math.ceil(robot.unit * 48)
    }

    Item {
        anchors.centerIn: parent
        width: 48 * robot.unit
        height: width
        visible: robot.canMove

        KSvg.Svg {
            id: artworkLayers
            multipleImages: true
            imagePath: decodeURIComponent(robot.artwork.toString().replace(/^file:\/\//, ""))
        }
        KSvg.SvgItem {
            anchors.fill: parent
            svg: artworkLayers
            elementId: "shell"
        }
        KSvg.SvgItem {
            anchors.fill: parent
            svg: artworkLayers
            elementId: "beacon"
            // Pip's antenna joins the back of the housing.
            z: robot.design.id === "pip" ? -1 : 1
            opacity: 1 - (robot.design.dim || 0) * pose.gesture
            transform: [
                Scale {
                    origin.x: robot.design.pivot.x * robot.unit
                    origin.y: robot.design.pivot.y * robot.unit
                    xScale: 1 + (robot.design.zoom || 0) * pose.gesture
                    yScale: xScale
                },
                Rotation {
                    origin.x: robot.design.pivot.x * robot.unit
                    origin.y: robot.design.pivot.y * robot.unit
                    angle: (robot.design.turn || 0) * pose.gesture
                },
                Translate {
                    x: (robot.design.slide || 0) * robot.unit * pose.gesture
                    y: -(robot.design.rise || 0) * robot.unit * pose.gesture
                }
            ]
        }
    }

    Item {
        anchors.centerIn: parent
        width: 48
        height: 48
        scale: robot.unit
        visible: robot.canMove && !robot.expressionSource

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
