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
 * In edge-docked mode it rests as a narrow tab on the nearer side of the
 * screen. Hover reveals the shortcut and dragging it chooses its new side.
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
PositionedWindow {
    id: floating

    required property AssistantSession session
    property int posX: -1
    property int posY: -1
    property real idleOpacity: 0.4
    required property IconActivity activity
    property bool busy: false
    property bool useRobotMascot: false
    property int selectedIndex: -1
    property int widthInGridUnits: 30
    property int heightInGridUnits: 26
    property bool expanded: false
    property bool toolOpened: false
    property bool menuOpen: false
    readonly property alias inputText: view.inputText

    readonly property real shortcutScale: (session.ui.floating_size ?? 100) / 100
    readonly property int size: Math.round((Kirigami.Units.iconSizes.large + Kirigami.Units.largeSpacing) * shortcutScale)
    // -1 means "never placed": near the bottom right, clear of a bottom panel.
    readonly property int placedX: clampX(posX < 0 ? screenWidth - size - Kirigami.Units.gridUnit * 2 : posX)
    readonly property int placedY: clampY(posY < 0 ? screenHeight - size - Kirigami.Units.gridUnit * 5 : posY)
    // Open, the window grows away from the screen edge the button is near.
    readonly property bool growLeft: placedX + size / 2 > screenWidth / 2
    readonly property bool growUp: placedY + size / 2 > screenHeight / 2
    readonly property bool docked: session.ui.floating_docked === true
    readonly property int shortcutX: docked ? (growLeft ? screenWidth - size : 0) : placedX
    readonly property int tabWidth: Math.min(size, 8)
    readonly property int tabHeight: Math.min(48, Math.round(size * 2 / 3))
    property bool dockHovered: false
    property real dockSlide: !docked || dockHovered || mouse.pressed || menuOpen || expanded ? 1 : 0
    Behavior on dockSlide {
        enabled: floating.docked && !floating.expanded && Kirigami.Units.longDuration > 1
        NumberAnimation { duration: Math.max(140, Kirigami.Units.shortDuration); easing.type: Easing.OutCubic }
    }
    // Grow the input surface once on entry, then slide the face within it. At rest
    // the native surface is only the tab, so nearby application controls receive clicks.
    readonly property bool tabOnly: docked && dockSlide === 0 && !dockHovered && !expanded
    readonly property int closedWidth: tabOnly ? tabWidth : size
    readonly property int closedHeight: tabOnly ? tabHeight : size

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

    /** Where the window goes for its current size: the button's corner stays put. */
    function layout() {
        if (mouse.dragging || view.windowMoveInProgress) {
            return;
        }
        if (expanded) {
            placeResizedPopup(openHeight, growLeft && reveal < 1 ? openWidth - width : 0);
            return;
        }
        const top = placedY + Math.round((size - closedHeight) / 2);
        place(growLeft ? shortcutX + size - width : shortcutX, growUp ? top + closedHeight - height : top);
    }

    function anchorOnOpen() {
        const left = growLeft ? shortcutX + size - openWidth : shortcutX;
        const top = growUp ? placedY + size - openHeight : placedY;
        anchorPopup(popupPosition.x >= 0 ? popupPosition.x : left,
                    popupPosition.y >= 0 ? popupPosition.y : top, openHeight);
    }

    function open() {
        if (expanded)
            return;
        toolOpened = view.fullSizeTool;
        anchorOnOpen();
        floating.expanded = true;
        layout();
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
            layout();
            floating.dismissed();
        }
    }

    function setInput(text) {
        view.setInput(text);
    }

    function clearInput() {
        view.clearInput();
    }

    width: Math.round(closedWidth + (openWidth - closedWidth) * reveal)
    height: Math.round(closedHeight + (openHeight - closedHeight) * reveal)
    visible: true
    title: i18n("Happy Bot")

    LayerShell.Window.scope: "happy-bot-button"
    LayerShell.Window.keyboardInteractivity: expanded ? LayerShell.Window.KeyboardInteractivityOnDemand
                                                      : LayerShell.Window.KeyboardInteractivityNone

    Component.onCompleted: layout()
    onSizeChanged: layout()
    onWidthChanged: layout()
    onHeightChanged: layout()
    onOpenHeightChanged: {
        if (!expanded)
            return;
        if (view.fullSizeTool)
            toolOpened = true;
        else if (!toolOpened && !session.hasTranscript)
            anchorOnOpen();
        layout();
    }
    onShortcutXChanged: layout()
    onGrowLeftChanged: layout()
    onGrowUpChanged: layout()
    onPlacedYChanged: layout()
    // A click anywhere else takes focus away: close, as the panel popup does; not while `holdOpen`
    // (the application is briefly made active for a "Help with …" screenshot).
    property bool holdOpen: false
    onActiveChanged: if (!active && expanded && !holdOpen) close()

    Timer {
        id: tuckDelay
        interval: 260
        onTriggered: if (!mouse.containsMouse && !mouse.pressed) floating.dockHovered = false
    }

    // --- open: Happy Bot itself ------------------------------------------------
    Item {
        anchors.fill: parent
        visible: floating.reveal > 0
        opacity: floating.reveal
        clip: true

        ResultsView {
            id: view

            // Pinned to the button's corner, so it slides out of the button.
            x: floating.growLeft && floating.reveal < 1 ? parent.width - width : 0
            y: (floating.expanded ? floating.popupGrowsUp : floating.growUp) ? parent.height - height : 0
            session: floating.session
            width: Math.min(implicitWidth, floating.screenWidth)
            height: Math.min(implicitHeight, floating.screenHeight)
            useRobotMascot: floating.useRobotMascot
            fieldAtBottom: floating.growUp
            backAtTop: view.fullSizeTool && !floating.popupGrowsUp
            selectedIndex: floating.selectedIndex
            widthInGridUnits: floating.widthInGridUnits
            heightInGridUnits: floating.heightInGridUnits

            windowPosition: () => floating.screenPosition
            onWindowMoved: position => floating.movePopup(position)

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

    // --- closed: the shortcut and its edge tab -------------------------------------
    Item {
        x: floating.growLeft ? parent.width - width : 0
        y: floating.growUp ? parent.height - height : 0
        width: floating.closedWidth
        height: floating.closedHeight
        clip: true
        visible: floating.reveal < 1
        opacity: 1 - floating.reveal

        Item {
            width: floating.size
            height: width
            x: Math.round((floating.growLeft ? 1 : -1) * (1 - floating.dockSlide) * width)
            y: Math.round((parent.height - height) / 2)
            visible: floating.dockSlide > 0
            opacity: mouse.containsMouse || mouse.pressed || floating.busy || floating.activity.recording ? 1 : floating.idleOpacity

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

            MascotIcon {
                anchors.centerIn: parent
                width: Math.round(Kirigami.Units.iconSizes.medium * floating.shortcutScale)
                height: width
                activity: floating.activity
                mascot: floating.useRobotMascot
                robotStyle: floating.session.ui.robot_style ?? "pip"
                animate: floating.session.ui.mascot_animations !== false
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

        Rectangle {
            width: floating.tabWidth * 2
            height: floating.tabHeight
            x: floating.growLeft ? parent.width - floating.tabWidth : -floating.tabWidth
            anchors.verticalCenter: parent.verticalCenter
            radius: floating.tabWidth
            visible: floating.docked && floating.dockSlide < 1
            opacity: (1 - floating.dockSlide) * (mouse.containsMouse || floating.activity.recording ? 1 : floating.idleOpacity)
            // Carry the note and recording light colours over from the mascot artwork.
            color: floating.activity.recording ? "#ff696b" : floating.activity.expression === "nudge" ? "#ffc463"
                : floating.useRobotMascot ? Look.mascotAccent : Kirigami.Theme.highlightColor
            border.width: 1
            border.color: Kirigami.Theme.textColor
        }

        MouseArea {
            id: mouse

            property point pressedAt
            property point dragOrigin
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
            Accessible.description: floating.activity.description()
            Accessible.onPressAction: floating.clicked()

            onEntered: {
                tuckDelay.stop();
                floating.dockHovered = true;
            }
            onExited: tuckDelay.restart()
            onCanceled: {
                dragging = false;
                floating.layout();
                tuckDelay.restart();
            }

            // Layer-shell coordinates are screen-relative. Add the current margins
            // to the event position so resizing a right-hand tab keeps the grab point.
            function screenPoint(event) {
                const point = mapToItem(floating.contentItem, event.x, event.y);
                const position = floating.screenPosition;
                return Qt.point(position.x + point.x, position.y + point.y);
            }

            onPressed: event => {
                pressedAt = screenPoint(event);
                dragOrigin = Qt.point(floating.shortcutX, floating.placedY);
                dragging = false;
            }
            onPositionChanged: event => {
                if (!pressed || !(pressedButtons & Qt.LeftButton)) {
                    return;
                }
                const point = screenPoint(event);
                const dx = point.x - pressedAt.x;
                const dy = point.y - pressedAt.y;
                if (!dragging && Math.abs(dx) + Math.abs(dy) < Kirigami.Units.smallSpacing * 2) {
                    return;
                }
                dragging = true;
                currentX = floating.clampX(dragOrigin.x + dx);
                currentY = floating.clampY(dragOrigin.y + dy);
                floating.place(currentX, currentY);
            }
            onReleased: event => {
                if (!containsMouse) tuckDelay.restart();
                if (dragging) {
                    dragging = false;
                    const right = currentX + floating.size / 2 > floating.screenWidth / 2;
                    const snapX = right ? floating.screenWidth - floating.size : 0;
                    floating.place(floating.docked ? snapX : currentX, currentY);
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
