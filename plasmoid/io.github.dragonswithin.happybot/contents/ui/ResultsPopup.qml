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
 * Two behaviours, chosen by `takesFocus`:
 *
 * - true (the icon form): the window takes keyboard focus when shown, puts
 *   the cursor in its field, and hides itself when it loses focus (a click
 *   anywhere else). Typing here keeps the panel from ever holding focus,
 *   which is what draws Plasma's blue panel focus indicator.
 * - false (the search-bar form, PanelBar.qml): the field is hidden, the
 *   window is a tooltip-type window that never accepts focus, so the panel
 *   field keeps focus and its keys while the popup's buttons still take
 *   clicks. main.qml shows and hides it; `barText` is the panel's text.
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
    property bool showConversation: false
    property bool takesFocus: true
    property string barText: ""
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

    type: takesFocus ? PlasmaCore.Dialog.AppletPopup : PlasmaCore.Dialog.Tooltip
    flags: takesFocus ? Qt.Dialog : Qt.WindowDoesNotAcceptFocus
    hideOnWindowDeactivate: takesFocus
    backgroundHints: PlasmaCore.Dialog.StandardBackground

    onVisibleChanged: {
        if (visible) {
            if (takesFocus) {
                requestActivate();
                resultsView.focusInput();
            }
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
        showField: popup.takesFocus
        barText: popup.barText
        showConversation: popup.showConversation
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
