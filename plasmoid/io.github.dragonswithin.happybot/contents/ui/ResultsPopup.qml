/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick

import org.kde.plasma.core as PlasmaCore

/**
 * The assistant's popup window: it opens next to the panel icon or bar
 * and holds ResultsView.qml, including the field the user types into. This
 * file owns only window behaviour; what is shown is in ResultsView.qml.
 *
 * The panel icon, shortcut and inline search bar all open the same focused
 * composer. The dialog stays anchored to its panel and closes on focus loss.
 *
 * `location` is the panel's edge; the field goes on the side facing the
 * panel. `hiddenAt` records when the window last hid, so main.qml can tell
 * that a click on the icon was the click that just closed it. The view's
 * signals are re-emitted unchanged; `dismissed` is emitted whenever it hides.
 */
PlasmaCore.Dialog {
    id: popup

    required property AssistantSession session
    property alias useRobotMascot: resultsView.useRobotMascot
    readonly property alias inputText: resultsView.inputText
    property int selectedIndex: -1
    property int widthInGridUnits: 30
    property int heightInGridUnits: 26
    property real hiddenAt: 0

    signal queryEdited(string text)
    signal accepted(string text)
    signal selectionMove(int delta)
    signal completeRequested()
    signal hitActivated(string location)
    signal resultActivated(var hit)
    signal fileActionRequested(var hit, string action)
    signal filesDropped(var paths)
    signal closeRequested()
    signal settingsRequested()
    signal dismissed()

    type: PlasmaCore.Dialog.AppletPopup
    flags: Qt.Dialog
    hideOnWindowDeactivate: true
    backgroundHints: PlasmaCore.Dialog.NoBackground


    onVisibleChanged: {
        if (visible) {
            requestActivate();
            resultsView.focusInput();
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

    mainItem: ResultsView {
        id: resultsView

        session: popup.session
        fieldAtBottom: popup.location === PlasmaCore.Types.BottomEdge
        selectedIndex: popup.selectedIndex
        widthInGridUnits: popup.widthInGridUnits
        heightInGridUnits: popup.heightInGridUnits

        onQueryEdited: text => popup.queryEdited(text)
        onAccepted: text => popup.accepted(text)
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
