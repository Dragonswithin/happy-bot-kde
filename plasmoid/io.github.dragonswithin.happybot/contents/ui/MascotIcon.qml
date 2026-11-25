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
    readonly property bool moving: visible && animate && Kirigami.Units.longDuration > 1
    readonly property bool hot: mascot && activity.hot && !activity.recording
    readonly property string transfer: mascot && !activity.recording ? activity.transfer : ""
    readonly property real unit: Math.min(width, height) / 48

    function artwork(name: string): string {
        return name ? Qt.resolvedUrl("../images/reactions/" + name + ".svg").toString() : "";
    }

    Image {
        anchors.fill: parent
        fillMode: Image.PreserveAspectFit
        sourceSize.width: Math.ceil(face.unit * 48)
        source: face.mascot ? Look.robotIcon : ""
    }
    Kirigami.Icon {
        anchors.fill: parent
        visible: !face.mascot
        source: face.activity.recording ? "audio-input-microphone" : Look.assistantIcon(false)
    }

    Image {
        anchors.fill: parent
        fillMode: Image.PreserveAspectFit
        sourceSize.width: Math.ceil(face.unit * 48)
        source: face.artwork(face.hot ? "hot-face" : "")
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

    Image {
        anchors.fill: parent
        fillMode: Image.PreserveAspectFit
        sourceSize.width: Math.ceil(face.unit * 48)
        source: face.artwork(face.mascot && face.activity.recording ? "recording" : "")
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
