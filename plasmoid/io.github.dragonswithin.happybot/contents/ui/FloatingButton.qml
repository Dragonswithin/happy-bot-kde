/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Window

import org.kde.kirigami as Kirigami
import org.kde.layershell as LayerShell

/**
 * The floating Happy Bot: a small round button above other windows,
 * anywhere on the screen, that opens into Happy Bot itself right where it
 * is. main.qml creates it when Happy Bot runs as its own app; it needs
 * neither the panel icon nor the panel bar.
 *
 * It is a layer-shell surface (LayerShellQt, the protocol Plasma's own
 * panels use) on the "top" layer: above ordinary windows, below full-screen
 * ones. Closed, it never takes keyboard focus, so the application the user
 * is in stays active and can be named when the button is clicked. Its
 * position is its distance from the screen's top left (`posX`, `posY`,
 * logical pixels), applied as layer-shell margins; margins take effect only
 * with a new frame, so every move and resize also redraws.
 *
 * Closed: a click emits `clicked` (main.qml then calls `open`); dragging
 * more than a few pixels moves it, kept on the screen, and emits
 * `moved(x, y)` on release so main.qml can save the place; a right click
 * emits `menuRequested`. It is drawn at `idleOpacity`, fully under the
 * pointer, with a ring turning while `busy`.
 *
 * Open (`expanded`): the window grows from the button toward the middle of
 * the screen and holds ResultsView.qml, the same view as the panel popup:
 * the "Ask or search anything" field on the side nearest the button, then
 * file matches or the conversation. It takes keyboard focus while open
 * (layer-shell "on demand") and closes when the user clicks elsewhere, or
 * through the view's close button or Escape (`closeRequested`, which
 * main.qml answers with `close`). The view's signals are re-emitted
 * unchanged, like ResultsPopup.qml's, so main.qml treats either the same;
 * `dismissed` is emitted whenever it closes.
 */
Window {
    id: floating

    required property AssistantSession session
    property int posX: -1
    property int posY: -1
    property real idleOpacity: 0.4
    property string iconSource: "tools-wizard"
    property bool busy: false
    property bool useRobotMascot: false
    property int selectedIndex: -1
    property int widthInGridUnits: 30
    property int heightInGridUnits: 26
    property bool expanded: false

    readonly property int size: Kirigami.Units.iconSizes.large + Kirigami.Units.largeSpacing
    readonly property int screenWidth: screen ? screen.width : 1280
    readonly property int screenHeight: screen ? screen.height : 720
    // -1 means "never placed": near the bottom right, clear of a bottom panel.
    readonly property int placedX: posX < 0 ? screenWidth - size - Kirigami.Units.gridUnit * 2 : clampX(posX)
    readonly property int placedY: posY < 0 ? screenHeight - size - Kirigami.Units.gridUnit * 5 : clampY(posY)
    // Open, the window grows away from the screen edge the button is near.
    readonly property bool growLeft: placedX + size / 2 > screenWidth / 2
    readonly property bool growUp: placedY + size / 2 > screenHeight / 2
    // 0 closed, 1 open; animated, so the field slides out of the button.
    property real reveal: expanded ? 1 : 0
    Behavior on reveal {
        NumberAnimation { duration: Kirigami.Units.shortDuration; easing.type: Easing.OutCubic }
    }
    // Open, the window is exactly the view's size.
    readonly property int openWidth: Math.min(screenWidth, Math.max(1, view.width))
    readonly property int openHeight: Math.min(screenHeight, Math.max(1, view.height))

    signal clicked()
    signal menuRequested()
    signal moved(int x, int y)
    signal queryEdited(string text)
    signal accepted(string text)
    signal askRequested(string text)
    signal talkRequested()
    signal selectionMove(int delta)
    signal completeRequested()
    signal hitActivated(string location)
    signal resultActivated(var hit)
    signal fileActionRequested(var hit, string action)
    signal filesDropped(var paths)
    signal closeRequested()
    signal settingsRequested()
    signal dismissed()

    function clampX(value) {
        return Math.max(0, Math.min(screenWidth - size, value));
    }

    function clampY(value) {
        return Math.max(0, Math.min(screenHeight - size, value));
    }

    /** Puts the window's top left at x, y (logical pixels, from the screen's top left) and redraws. */
    function place(x, y) {
        floating.LayerShell.Window.margins = ({ left: Math.max(0, x), top: Math.max(0, y), right: 0, bottom: 0 });
        floating.requestUpdate();
    }

    /** Where the window goes for its current size: the button's corner stays put. */
    function layout() {
        if (mouse.dragging) {
            return;
        }
        place(growLeft ? placedX + size - width : placedX, growUp ? placedY + size - height : placedY);
    }

    function open() {
        floating.expanded = true;
        // Ask for keyboard focus once the "may take the keyboard" change has reached the compositor.
        Qt.callLater(function() {
            floating.requestActivate();
            view.focusInput();
        });
    }

    /** Takes the keyboard back after another window was briefly made active (a screenshot for "Help with …"). */
    function refocus() {
        if (floating.expanded) {
            floating.requestActivate();
            view.focusInput();
        }
    }

    function close() {
        if (floating.expanded) {
            floating.expanded = false;
            floating.dismissed();
        }
    }

    function setInput(text) {
        view.setInput(text);
    }

    function clearInput() {
        view.clearInput();
    }

    width: Math.round(size + (openWidth - size) * reveal)
    height: Math.round(size + (openHeight - size) * reveal)
    visible: true
    color: "transparent"
    flags: Qt.FramelessWindowHint
    title: i18n("Happy Bot")

    LayerShell.Window.scope: "happy-bot-button"
    LayerShell.Window.layer: LayerShell.Window.LayerTop
    LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorLeft
    LayerShell.Window.keyboardInteractivity: expanded ? LayerShell.Window.KeyboardInteractivityOnDemand
                                                      : LayerShell.Window.KeyboardInteractivityNone
    // Not pushed aside by panels' reserved space: the position is from the screen's own corner.
    LayerShell.Window.exclusionZone: -1

    Component.onCompleted: layout()
    onWidthChanged: layout()
    onHeightChanged: layout()
    onPlacedXChanged: layout()
    onPlacedYChanged: layout()
    // A click anywhere else takes focus away: close, as the panel popup does; not while `holdOpen`
    // (the application is briefly made active for a "Help with …" screenshot).
    property bool holdOpen: false
    onActiveChanged: if (!active && expanded && !holdOpen) close()

    // --- open: Happy Bot itself ------------------------------------------------
    Item {
        anchors.fill: parent
        visible: floating.reveal > 0
        opacity: floating.reveal
        clip: true

        ResultsView {
            id: view

            // Pinned to the button's corner, so it slides out of the button.
            x: floating.growLeft ? parent.width - width : 0
            y: floating.growUp ? parent.height - height : 0
            session: floating.session
            width: Math.min(implicitWidth, floating.screenWidth)
            height: Math.min(implicitHeight, floating.screenHeight)
            useRobotMascot: floating.useRobotMascot
            fieldAtBottom: floating.growUp
            selectedIndex: floating.selectedIndex
            widthInGridUnits: floating.widthInGridUnits
            heightInGridUnits: floating.heightInGridUnits

            onQueryEdited: text => floating.queryEdited(text)
            onAccepted: text => floating.accepted(text)
            onAskRequested: text => floating.askRequested(text)
            onTalkRequested: floating.talkRequested()
            onSelectionMove: delta => floating.selectionMove(delta)
            onCompleteRequested: floating.completeRequested()
            onHitActivated: location => floating.hitActivated(location)
            onResultActivated: hit => floating.resultActivated(hit)
            onFileActionRequested: (hit, action) => floating.fileActionRequested(hit, action)
            onFilesDropped: paths => floating.filesDropped(paths)
            onCloseRequested: floating.closeRequested()
            onSettingsRequested: floating.settingsRequested()
        }
    }

    // --- closed: the round button ------------------------------------------------
    Item {
        id: face

        x: floating.growLeft ? parent.width - width : 0
        y: floating.growUp ? parent.height - height : 0
        width: floating.size
        height: floating.size
        visible: floating.reveal < 1
        opacity: (1 - floating.reveal) * (mouse.containsMouse || mouse.pressed || floating.busy ? 1 : floating.idleOpacity)

        Behavior on opacity {
            enabled: !floating.expanded
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

        MouseArea {
            id: mouse

            property point pressedAt
            property int currentX
            property int currentY
            property bool dragging: false

            anchors.fill: parent
            enabled: !floating.expanded
            hoverEnabled: true
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            cursorShape: dragging ? Qt.ClosedHandCursor : Qt.PointingHandCursor

            Accessible.role: Accessible.Button
            Accessible.name: i18n("Ask Happy Bot about this application")
            Accessible.onPressAction: floating.clicked()

            onPressed: event => {
                pressedAt = Qt.point(event.x, event.y);
                currentX = floating.placedX;
                currentY = floating.placedY;
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
}
