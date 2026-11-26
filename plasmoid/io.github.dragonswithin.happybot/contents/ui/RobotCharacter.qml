// SPDX-License-Identifier: MIT
// Articulate the original 48-unit mascot's visor, antenna and waving hand.
pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Shapes
import org.kde.kirigami as Kirigami

Item {
    id: robot
    property bool animate: true
    property bool attentive: false
    property bool greetOnShow: false
    property string expressionSource: ""
    readonly property bool canMove: animate && visible && width > 0 && height > 0
        && Window.window !== null && Window.window.visible && Window.window.visibility !== Window.Minimized
        && Kirigami.Units.longDuration > 1
    readonly property real unit: Math.min(width, height) / 48
    readonly property bool performing: canMove && (hello.running || pose.eyelid !== 1 || pose.gaze !== 0)
    property bool ready: false
    Accessible.ignored: true

    function duration(ms: real): int {
        // Give gestures time to read even when Plasma's UI transitions are fast.
        return Math.round(ms * Math.max(1, Kirigami.Units.longDuration / 200));
    }

    function greet() {
        if (ready && canMove && !hello.running) hello.start();
    }

    function syncVisibility() {
        if (!ready) return;
        if (!canMove) hello.stop();
        else if (greetOnShow || attentive) greet();
    }

    Component.onCompleted: { ready = true; syncVisibility(); }
    onCanMoveChanged: syncVisibility()
    onAttentiveChanged: if (attentive) greet()
    onGreetOnShowChanged: if (greetOnShow) greet()

    QtObject {
        id: pose
        objectName: "characterPose"
        property real lift: 0       // The hand unfolds as the head makes room beside it.
        property real hop: 0        // Vertical travel, in artwork units.
        property real wrist: 0      // The hand's rotation at its cuff, in degrees.
        property real aerial: 0
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
        id: hello
        // Anticipation, spring up, two waves, then tuck the hand back in.
        ParallelAnimation {
            Beat { property: "eyelid"; to: 1; ms: 180 }
            Beat { property: "gaze"; to: 0; ms: 180 }
            Beat { property: "hop"; from: 0; to: 2.5; ms: 180 }
            Beat { property: "aerial"; from: 0; to: 10; ms: 180 }
        }
        ParallelAnimation {
            Beat { property: "lift"; from: 0; to: 1; ms: 420; easing.type: Easing.OutCubic }
            SequentialAnimation {
                Beat { property: "hop"; to: -4; ms: 180; easing.type: Easing.OutQuad }
                Beat { property: "hop"; to: 0; ms: 240; easing.type: Easing.InQuad }
            }
            SequentialAnimation {
                Beat { property: "aerial"; to: -22; ms: 180 }
                Beat { property: "aerial"; to: 15; ms: 240 }
            }
        }
        ParallelAnimation {
            SequentialAnimation {
                // Let the raised palm read before the first sweep.
                PauseAnimation { duration: robot.duration(220) }
                Beat { property: "wrist"; to: -27; ms: 350 }
                Beat { property: "wrist"; to: 22; ms: 460 }
                Beat { property: "wrist"; to: -25; ms: 440 }
                Beat { property: "wrist"; to: 18; ms: 450 }
                Beat { property: "wrist"; to: -4; ms: 330 }
                PauseAnimation { duration: robot.duration(250) }
            }
            SequentialAnimation {
                Beat { property: "aerial"; to: -8; ms: 260 }
                Beat { property: "aerial"; to: 3; ms: 230 }
                Beat { property: "aerial"; to: 0; ms: 180 }
            }
        }
        ParallelAnimation {
            Beat { property: "lift"; to: 0; ms: 460 }
            Beat { property: "wrist"; to: 0; ms: 390 }
            SequentialAnimation {
                Beat { property: "hop"; to: 2; ms: 200 }
                Beat { property: "hop"; to: 0; ms: 260 }
            }
        }
        onStopped: {
            pose.lift = 0;
            pose.hop = 0;
            pose.wrist = 0;
            pose.aerial = 0;
            pose.eyelid = 1;
            pose.gaze = 0;
        }
    }

    SequentialAnimation {
        running: robot.ready && robot.canMove && !hello.running && !robot.expressionSource
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
        // A greeting picks up the current gaze and blink during its anticipation.
        onStopped: if (!hello.running) { pose.eyelid = 1; pose.gaze = 0; }
    }

    // Keep the same drawing between glances. The motion-off option uses the shipped icon.
    Image {
        anchors.fill: parent
        visible: !robot.canMove
        fillMode: Image.PreserveAspectFit
        source: Look.robotIcon
        sourceSize.width: Math.ceil(robot.unit * 48)
    }

    Item {
        anchors.centerIn: parent
        width: 48
        height: 48
        scale: robot.unit
        visible: robot.canMove || robot.expressionSource !== ""

        component Layer: Image {
            anchors.fill: parent
            sourceSize.width: Math.ceil(robot.unit * 48)
        }

        Item {
            id: arm
            visible: pose.lift > 0
            x: 26 + 12.5 * pose.lift
            y: 32 - 9 * pose.lift + pose.hop
            // A telescoping forearm joins the wrist to the ear motor.
            Rectangle {
                x: -11; y: 1; width: 14; height: 4.5; radius: height / 2
                color: "#5bb6b3"
                border.color: "#183840"; border.width: 1.3
                rotation: -35
            }
            Image {
                x: -8; y: -15; width: 16; height: 18
                sourceSize.width: Math.ceil(16 * robot.unit)
                source: "../images/character/hand.svg"
                transform: Rotation {
                    origin.x: 8; origin.y: 15
                    angle: 70 * (1 - pose.lift) + pose.wrist
                }
            }
        }

        Item {
            id: head
            width: 48
            height: 48
            x: -6.2 * pose.lift
            y: pose.hop + 3 * pose.lift
            scale: 1 - 0.285 * pose.lift

            Item {
                anchors.fill: parent
                visible: robot.canMove
                Layer {
                    source: "../images/character/aerial.svg"
                    transform: Rotation { origin.x: 25; origin.y: 15; angle: pose.aerial }
                }
                Layer { source: "../images/character/shell.svg" }

                component Eye: Shape {
                    width: 9; height: 10
                    y: 20
                    // The open capsule bends into a happy arch. Closing the lid keeps its center fixed.
                    transform: Scale { origin.y: 5; yScale: pose.eyelid }
                    ShapePath {
                        fillColor: "transparent"
                        strokeColor: "#adfff1"
                        strokeWidth: 4 - pose.lift
                        capStyle: ShapePath.RoundCap
                        startX: 4 - 2.5 * pose.lift; startY: 4 + pose.lift
                        PathQuad {
                            controlX: 4; controlY: 5 - 6 * pose.lift
                            x: 4 + 2.5 * pose.lift; y: 6 - pose.lift
                        }
                    }
                }
                Eye { x: 13 + pose.gaze }
                Eye { x: 27 + pose.gaze }
                Shape {
                    anchors.fill: parent
                    ShapePath {
                        fillColor: "#adfff1"
                        strokeColor: "#adfff1"
                        strokeWidth: 2
                        joinStyle: ShapePath.RoundJoin
                        capStyle: ShapePath.RoundCap
                        startX: 21 - pose.lift; startY: 29
                        PathQuad { controlX: 24; controlY: 32.5 - 4 * pose.lift; x: 27 + pose.lift; y: 29 }
                        PathQuad { controlX: 24; controlY: 32.5 + 3.5 * pose.lift; x: 21 - pose.lift; y: 29 }
                    }
                }
            }
            Layer { source: robot.expressionSource }
        }
    }
}
