// SPDX-License-Identifier: MIT
pragma ComponentBehavior: Bound
import QtQuick
import org.kde.kirigami as Kirigami

// All drawings share the original mascot's 48-unit canvas. The tray installer
// composes these same layers at their resting positions into named theme icons.
Item {
    id: face

    required property IconActivity activity
    property bool mascot: true
    property bool animate: true
    property bool attentive: false
    readonly property bool moving: animate && visible && Window.window && Window.window.visible
                                   && Window.visibility !== Window.Minimized && Kirigami.Units.longDuration > 1
    readonly property string expression: mascot ? activity.expression : ""
    readonly property bool hot: expression === "hot"
    // The nudge's note uses the same corner as the network arrows.
    readonly property string transfer: mascot && !activity.recording && expression !== "nudge" ? activity.transfer : ""
    readonly property real unit: Math.min(width, height) / 48

    // One nod as the CPU gets busy, or one squeeze as memory gets tight.
    // Settle into the drawn pose for as long as the condition holds.
    transform: Scale {
        id: headScale
        origin.x: face.width / 2
        origin.y: face.height * 0.84
        SequentialAnimation on yScale {
            running: face.moving && face.expression === "busy"
            NumberAnimation { from: 1; to: 0.83; duration: Kirigami.Units.shortDuration }
            NumberAnimation { to: 1; duration: Kirigami.Units.longDuration; easing.type: Easing.OutCubic }
            onStopped: headScale.yScale = 1
        }
        SequentialAnimation on xScale {
            running: face.moving && face.expression === "memory"
            NumberAnimation { from: 1; to: 0.80; duration: Kirigami.Units.shortDuration }
            NumberAnimation { to: 1; duration: Kirigami.Units.longDuration; easing.type: Easing.OutCubic }
            onStopped: headScale.xScale = 1
        }
    }

    function artwork(name: string): string {
        return name ? Qt.resolvedUrl("../images/reactions/" + name + ".svg").toString() : "";
    }

    // Heat and recording have a dedicated visor and antenna to keep their
    // indicators readable. Other expressions ride on the character's moving head.
    RobotCharacter {
        anchors.fill: parent
        visible: face.mascot && !face.hot && !face.activity.recording
        animate: face.animate
        attentive: face.attentive
        expressionSource: visible ? face.artwork(face.expression) : ""
    }

    Image {
        anchors.fill: parent
        fillMode: Image.PreserveAspectFit
        sourceSize.width: Math.ceil(face.unit * 48)
        source: face.mascot && (face.hot || face.activity.recording) ? Look.robotIcon
              : face.activity.recording ? Look.activeMicrophoneIcon : ""
    }
    Kirigami.Icon {
        anchors.fill: parent
        visible: !face.mascot && !face.activity.recording
        source: Look.assistantIcon(false)
    }

    Image {
        anchors.fill: parent
        fillMode: Image.PreserveAspectFit
        sourceSize.width: Math.ceil(face.unit * 48)
        source: face.hot ? face.artwork("hot-face") : face.mascot && face.activity.recording ? face.artwork("recording") : ""
    }
    Image {
        id: drop
        width: parent.width
        height: parent.height
        fillMode: Image.PreserveAspectFit
        sourceSize.width: Math.ceil(face.unit * 48)
        source: face.artwork(face.hot ? "sweat" : "")
        NumberAnimation on y {
            running: face.hot && face.moving
            from: -4 * face.unit
            to: 0
            duration: 2 * Kirigami.Units.longDuration
            easing.type: Easing.OutBounce
            onStopped: drop.y = 0
        }
    }

    Image {
        id: packet
        width: parent.width
        height: parent.height
        fillMode: Image.PreserveAspectFit
        sourceSize.width: Math.ceil(face.unit * 48)
        property bool outgoing: false
        readonly property string direction: face.transfer === "transfer" && face.moving
            ? (outgoing ? "upload" : "download") : face.transfer
        source: face.artwork(direction)
        SequentialAnimation {
            id: sendPacket
            running: face.transfer.length > 0 && face.moving
            loops: Animation.Infinite
            NumberAnimation {
                target: packet; property: "y"
                from: packet.direction === "upload" ? 5 * face.unit : 0
                to: packet.direction === "upload" ? 0 : 5 * face.unit
                duration: 2 * Kirigami.Units.longDuration
                easing.type: Easing.InOutSine
            }
            PauseAnimation { duration: 3 * Kirigami.Units.longDuration }
            ScriptAction { script: packet.outgoing = !packet.outgoing }
            onStopped: { packet.y = 0; packet.outgoing = false; }
        }
    }

    // The microphone and red tally stay solid throughout capture. Only the
    // surrounding ring breathes, independently of what the microphone hears.
    Rectangle {
        id: tallyRing
        visible: face.mascot && face.activity.recording && face.moving
        width: 11 * face.unit
        height: width
        x: (face.width - 48 * face.unit) / 2 + 32 * face.unit - width / 2
        y: (face.height - 48 * face.unit) / 2 + 6 * face.unit - height / 2
        radius: width / 2
        border.width: 1.5 * face.unit
        border.color: "#ff777c"
        color: "transparent"
        SequentialAnimation on scale {
            running: tallyRing.visible
            loops: Animation.Infinite
            NumberAnimation { from: 0.88; to: 1.35; duration: 2 * Kirigami.Units.longDuration }
            NumberAnimation { from: 1.35; to: 0.88; duration: 2 * Kirigami.Units.longDuration }
        }
    }
}
