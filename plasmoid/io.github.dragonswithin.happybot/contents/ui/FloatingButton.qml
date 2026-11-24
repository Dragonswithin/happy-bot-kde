/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Window

import org.kde.kirigami as Kirigami
import org.kde.layershell as LayerShell

/**
 * The floating Happy Bot button: a small round window above other windows,
 * anywhere on the screen, faded while not in use. main.qml creates it when
 * the `floatingButton` setting is on.
 *
 * It is a layer-shell surface (LayerShellQt, the protocol Plasma's own
 * panels use) on the "top" layer: above ordinary windows, below full-screen
 * ones, never taking keyboard focus, so the application the user is in
 * stays active and can be named when the button is clicked. Its position is
 * its distance from the screen's top left (`posX`, `posY`, logical pixels),
 * applied as layer-shell margins. Margins take effect only with a new frame,
 * so every move also redraws.
 *
 * Pointer: a click emits `clicked`; dragging more than a few pixels moves
 * the button with the pointer, kept on the screen, and emits `moved(x, y)`
 * when released so main.qml can save the place; a right click emits
 * `menuRequested`. It is drawn at `idleOpacity` and fully under the pointer;
 * a ring turns while `busy`. It keeps no state beyond the drag in progress.
 */
Window {
    id: floating

    property int posX: -1
    property int posY: -1
    property real idleOpacity: 0.4
    property string iconSource: "tools-wizard"
    property bool busy: false

    readonly property int size: Kirigami.Units.iconSizes.large + Kirigami.Units.largeSpacing
    readonly property int screenWidth: screen ? screen.width : 1280
    readonly property int screenHeight: screen ? screen.height : 720
    // -1 means "never placed": near the bottom right, clear of a bottom panel.
    readonly property int placedX: posX < 0 ? screenWidth - size - Kirigami.Units.gridUnit * 2 : clampX(posX)
    readonly property int placedY: posY < 0 ? screenHeight - size - Kirigami.Units.gridUnit * 5 : clampY(posY)

    signal clicked()
    signal menuRequested()
    signal moved(int x, int y)

    function clampX(value) {
        return Math.max(0, Math.min(screenWidth - size, value));
    }

    function clampY(value) {
        return Math.max(0, Math.min(screenHeight - size, value));
    }

    function place(x, y) {
        floating.LayerShell.Window.margins = ({ left: x, top: y, right: 0, bottom: 0 });
        floating.requestUpdate();
    }

    width: size
    height: size
    visible: true
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus
    title: i18n("Happy Bot")

    LayerShell.Window.scope: "happy-bot-button"
    LayerShell.Window.layer: LayerShell.Window.LayerTop
    LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorLeft
    LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
    // Not pushed aside by panels' reserved space: the position is from the screen's own corner.
    LayerShell.Window.exclusionZone: -1

    Component.onCompleted: place(placedX, placedY)
    onPlacedXChanged: if (!mouse.dragging) place(placedX, placedY)
    onPlacedYChanged: if (!mouse.dragging) place(placedX, placedY)

    Item {
        id: face

        anchors.fill: parent
        opacity: mouse.containsMouse || mouse.pressed || floating.busy ? 1 : floating.idleOpacity

        Behavior on opacity {
            NumberAnimation { duration: Kirigami.Units.longDuration }
        }

        Rectangle {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.smallSpacing / 2
            radius: width / 2
            color: Qt.alpha(Kirigami.Theme.backgroundColor, 0.92)
            border.width: 1
            border.color: Qt.alpha(Kirigami.Theme.textColor, 0.2)
        }

        Kirigami.Icon {
            anchors.centerIn: parent
            width: Kirigami.Units.iconSizes.medium
            height: width
            source: floating.iconSource
        }

        // Turns while Happy Bot is working on a request.
        Rectangle {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.smallSpacing / 2
            radius: width / 2
            color: "transparent"
            border.width: 2
            border.color: Kirigami.Theme.highlightColor
            visible: floating.busy
            opacity: 0.8

            SequentialAnimation on opacity {
                running: floating.busy
                loops: Animation.Infinite
                NumberAnimation { from: 0.9; to: 0.2; duration: 800; easing.type: Easing.InOutSine }
                NumberAnimation { from: 0.2; to: 0.9; duration: 800; easing.type: Easing.InOutSine }
            }
        }
    }

    MouseArea {
        id: mouse

        property point pressedAt
        property int startX
        property int startY
        property int currentX
        property int currentY
        property bool dragging: false

        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: dragging ? Qt.ClosedHandCursor : Qt.PointingHandCursor

        Accessible.role: Accessible.Button
        Accessible.name: i18n("Ask Happy Bot about this application")
        Accessible.onPressAction: floating.clicked()

        onPressed: event => {
            pressedAt = Qt.point(event.x, event.y);
            startX = currentX = floating.placedX;
            startY = currentY = floating.placedY;
            dragging = false;
        }
        onPositionChanged: event => {
            if (!pressed || !(pressedButtons & Qt.LeftButton)) {
                return;
            }
            // The window moves under the pointer, so the press point stays at the same spot inside it.
            const dx = event.x - pressedAt.x;
            const dy = event.y - pressedAt.y;
            if (!dragging && Math.abs(dx) + Math.abs(dy) < Kirigami.Units.smallSpacing * 2) {
                return;
            }
            dragging = true;
            currentX = floating.clampX(currentX + dx);
            currentY = floating.clampY(currentY + dy);
            floating.place(currentX, currentY);
        }
        onReleased: event => {
            if (dragging) {
                dragging = false;
                floating.moved(currentX, currentY);
            } else if (event.button === Qt.RightButton) {
                floating.menuRequested();
            } else {
                floating.clicked();
            }
        }
    }
}
