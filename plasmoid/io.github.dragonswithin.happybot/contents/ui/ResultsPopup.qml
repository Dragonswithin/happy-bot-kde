/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Window

import org.kde.plasma.core as PlasmaCore
import org.kde.layershell as LayerShell

/**
 * The assistant's popup window: it opens next to the panel icon or bar
 * and holds ResultsView.qml, including the field the user types into. This
 * file owns only window behaviour; what is shown is in ResultsView.qml.
 *
 * The panel icon, shortcut and inline search bar all open the same focused
 * composer. The dialog starts anchored to its panel and closes on focus loss.
 *
 * `location` is the panel's edge; the field goes on the side facing the
 * panel. `hiddenAt` records when the window last hid, so main.qml can tell
 * that a click on the icon was the click that just closed it. The view's
 * signals are re-emitted unchanged; `dismissed` is emitted whenever it hides.
 */
Window {
    id: popup

    required property AssistantSession session
    property alias useRobotMascot: resultsView.useRobotMascot
    readonly property alias inputText: resultsView.inputText
    property int selectedIndex: -1
    property int widthInGridUnits: 30
    property int heightInGridUnits: 26
    property real hiddenAt: 0
    property Item anchorItem
    property int location: PlasmaCore.Types.Floating
    property point savedPosition: Qt.point(session.ui.panel_popup_x ?? -1, session.ui.panel_popup_y ?? -1)
    property point currentPosition
    property bool positionedByUser: savedPosition.x >= 0 && savedPosition.y >= 0
    screen: anchorItem?.Window.window?.screen ?? null

    function place(position) {
        currentPosition = Qt.point(
            Math.round(Math.max(0, Math.min(position.x, screen.width - width))),
            Math.round(Math.max(0, Math.min(position.y, screen.height - height))));
        LayerShell.Window.margins = ({ left: currentPosition.x, top: currentPosition.y, right: 0, bottom: 0 });
        x = resultsView.Screen.virtualX + currentPosition.x;
        y = resultsView.Screen.virtualY + currentPosition.y;
    }

    function restorePosition() {
        if (!screen || !anchorItem?.Window.window)
            return;
        if (positionedByUser) {
            place(savedPosition);
            return;
        }
        const topLeft = anchorItem.mapToGlobal(0, 0);
        let left = topLeft.x - resultsView.Screen.virtualX;
        let top = topLeft.y - resultsView.Screen.virtualY;
        const panel = anchorItem.Window.window;
        if (location === PlasmaCore.Types.LeftEdge)
            left = panel.width;
        else if (location === PlasmaCore.Types.RightEdge)
            left = screen.width - panel.width - width;
        else if (location === PlasmaCore.Types.TopEdge)
            top = panel.height;
        else if (location === PlasmaCore.Types.BottomEdge)
            top = screen.height - panel.height - height;
        else
            top += anchorItem.height;
        place(Qt.point(left, top));
    }

    onWidthChanged: Qt.callLater(restorePosition)
    onHeightChanged: Qt.callLater(restorePosition)
    onScreenChanged: Qt.callLater(restorePosition)

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

    width: Math.min(resultsView.implicitWidth, screen?.width ?? resultsView.implicitWidth)
    height: Math.min(resultsView.implicitHeight, screen?.height ?? resultsView.implicitHeight)
    color: "transparent"
    flags: Qt.Dialog | Qt.FramelessWindowHint
    title: i18n("Happy Bot")
    LayerShell.Window.scope: "happy-bot-panel-popup"
    LayerShell.Window.layer: LayerShell.Window.LayerTop
    LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorLeft
    LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityOnDemand
    LayerShell.Window.exclusionZone: -1

    // Hold focus-loss dismissal during a "Help with …" screenshot.
    property bool holdOpen: false
    onActiveChanged: if (!active && visible && !holdOpen) visible = false

    /** Takes the keyboard back after another window was briefly made active. */
    function refocus() {
        if (visible) {
            requestActivate();
            resultsView.focusInput();
        }
    }

    onVisibleChanged: {
        if (visible) {
            restorePosition();
            Qt.callLater(refocus);
        } else {
            popup.hiddenAt = Date.now();
            popup.dismissed();
        }
    }

    function clearInput() {
        resultsView.clearInput();
    }

    function setInput(text) {
        resultsView.setInput(text);
    }

    ResultsView {
        id: resultsView

        anchors.fill: parent
        session: popup.session
        fieldAtBottom: popup.location === PlasmaCore.Types.BottomEdge
        selectedIndex: popup.selectedIndex
        widthInGridUnits: popup.widthInGridUnits
        heightInGridUnits: popup.heightInGridUnits

        windowPosition: () => popup.currentPosition
        onWindowMoved: (position, finished) => {
            popup.place(position);
            if (finished) {
                popup.savedPosition = popup.currentPosition;
                popup.session.saveUi({ panel_popup_x: popup.savedPosition.x, panel_popup_y: popup.savedPosition.y });
            }
        }

        onQueryEdited: text => popup.queryEdited(text)
        onAccepted: text => popup.accepted(text)
        onAskRequested: text => popup.askRequested(text)
        onTalkRequested: popup.talkRequested()
        onSelectionMove: delta => popup.selectionMove(delta)
        onCompleteRequested: popup.completeRequested()
        onHitActivated: location => popup.hitActivated(location)
        onResultActivated: hit => popup.resultActivated(hit)
        onFileActionRequested: (hit, action) => popup.fileActionRequested(hit, action)
        onFilesDropped: paths => popup.filesDropped(paths)
        onCloseRequested: popup.closeRequested()
        onSettingsRequested: popup.settingsRequested()
    }
}
