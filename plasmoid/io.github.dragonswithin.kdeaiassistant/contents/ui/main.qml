/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick

import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.extras as PlasmaExtras
import org.kde.plasma.plasmoid

/**
 * Root of the panel applet. It composes the three visual parts around one
 * AssistantSession and owns the rules that connect them:
 *
 * - Which form the panel shows. A horizontal panel gets the inline text
 *   field (PanelBar.qml). A vertical panel, or the `inputInPopup` setting,
 *   gets the icon (CompactRepresentation.qml) and typing happens inside
 *   ResultsPopup.qml instead.
 * - Keyboard focus. A panel only accepts key input while an applet reports
 *   AcceptingInputStatus, so `wantsInput` drives `Plasmoid.status` and is
 *   set before the field is focused and cleared when the field loses focus.
 * - Popup visibility (`updatePopup`). Clicking or focusing the field never
 *   opens the popup, with one exception: while an action is waiting for the
 *   user's approval the applet asks for attention, and focusing the field
 *   shows the conversation so the approval card is in front of them. In bar mode it is visible while the field has focus
 *   and there is something to show: file hits for the typed text, a search
 *   failure, or a conversation the user opened by submitting a request (or
 *   by pressing Enter in an empty field). Escape closes the conversation.
 *   In button mode the button toggles it.
 * - Typing. Text of two or more characters is sent to the instant file
 *   search after `searchDelay` of no typing. Down/Up move a selection
 *   through the hits. Enter opens the selected hit; with no selection it
 *   sends the text to the assistant.
 *
 * The applet's activation shortcut (set by the user in the applet's
 * Keyboard Shortcuts page) focuses the field or opens the popup.
 *
 * A right-click on the bar or the icon opens the applet's own small menu
 * (settings, new conversation, remove).
 *
 * The daemon's address and token belong to DaemonClient.qml. The settings
 * dialog (contents/config/config.qml) holds appearance options and the
 * assistant's own setup; `openSettings` shows it, which is where a "no model
 * yet" message sends the user.
 */
PlasmoidItem {
    id: root

    readonly property bool inputInPopup: Plasmoid.configuration.inputInPopup
        || Plasmoid.formFactor === PlasmaCore.Types.Vertical
    property bool wantsInput: false

    Plasmoid.icon: "search"
    Plasmoid.title: i18n("AI Assistant")
    Plasmoid.status: {
        if (wantsInput) {
            return PlasmaCore.Types.AcceptingInputStatus;
        }
        if (session.pendingApprovals > 0) {
            return PlasmaCore.Types.NeedsAttentionStatus;
        }
        return session.busy ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.PassiveStatus;
    }
    toolTipSubText: session.statusText
    activationTogglesExpanded: false
    preferredRepresentation: inputInPopup ? compactRepresentation : fullRepresentation

    // Bar mode: true once the user asked to see the conversation.
    property bool conversationOpen: false
    // Button mode: true while the button has the popup toggled open.
    property bool popupToggled: false
    readonly property bool barFocused: fullRepresentationItem ? fullRepresentationItem.inputFocused : false
    onBarFocusedChanged: updatePopup()
    property string pendingQuery: ""

    AssistantSession {
        id: session
        configuredUrl: Plasmoid.configuration.daemonUrl || ""
        onHitsChanged: {
            popup.selectedIndex = -1;
            root.updatePopup();
        }
        onSearchErrorCodeChanged: root.updatePopup()
    }

    Timer {
        id: searchDelay
        interval: 200
        onTriggered: session.searchFiles(root.pendingQuery)
    }

    ResultsPopup {
        id: popup
        session: session
        inputInPopup: root.inputInPopup
        showConversation: root.conversationOpen
        widthInGridUnits: Plasmoid.configuration.popupWidth
        heightInGridUnits: Plasmoid.configuration.popupHeight
        visualParent: root
        location: Plasmoid.location
        onQueryEdited: text => root.handleEdited(text)
        onAccepted: text => root.handleAccepted(text)
        onSelectionMove: delta => root.moveSelection(delta)
        onHitActivated: location => root.openHit(location)
        onDismissed: root.popupToggled = false
        onCloseRequested: root.closePopup()
        onSettingsRequested: root.openSettings()
    }

    compactRepresentation: CompactRepresentation {
        status: session.status
        iconName: Plasmoid.icon
        onClicked: {
            root.popupToggled = !popup.visible;
            root.updatePopup();
        }
        onMenuRequested: contextMenu.openRelative()
    }

    fullRepresentation: PanelBar {
        busy: session.busy
        statusText: session.pendingApprovals > 0 ? i18n("Waiting for your approval — click here")
            : session.needsSetup && session.status !== "offline" ? i18n("Type here, or press Enter to set up")
            : session.statusText
        offline: session.status === "offline" || session.pendingApprovals > 0 || session.needsSetup
        widthInGridUnits: Plasmoid.configuration.barWidth

        onFocusRequested: root.focusBar()
        onQueryEdited: text => root.handleEdited(text)
        onAccepted: text => root.handleAccepted(text)
        onSelectionMove: delta => root.moveSelection(delta)
        onDismissed: root.closePopup()
        onMenuRequested: contextMenu.openRelative()
        onInputFocusedChanged: {
            if (!inputFocused) {
                root.wantsInput = false;
            } else if (session.pendingApprovals > 0) {
                root.conversationOpen = true;
            }
            root.updatePopup();
        }
    }

    // The applet's own right-click menu. A text field in the panel takes
    // right-clicks for itself, so Plasma's standard widget menu is not
    // reachable there; this offers the entries a user needs from it.
    PlasmaExtras.Menu {
        id: contextMenu
        visualParent: root

        PlasmaExtras.MenuItem {
            text: i18n("Configure AI Assistant…")
            icon: "configure"
            onClicked: root.openSettings()
        }

        PlasmaExtras.MenuItem {
            text: i18n("New conversation")
            icon: "document-new"
            onClicked: session.newChat()
        }

        PlasmaExtras.MenuItem {
            separator: true
        }

        PlasmaExtras.MenuItem {
            text: i18n("Remove from panel")
            icon: "edit-delete"
            onClicked: Plasmoid.internalAction("remove").trigger()
        }
    }

    function openSettings() {
        root.closePopup();
        Plasmoid.internalAction("configure").trigger();
    }

    function updatePopup() {
        if (root.inputInPopup) {
            popup.visible = root.popupToggled;
            return;
        }
        const somethingToShow = root.conversationOpen
            || session.hits.length > 0
            || session.searchErrorCode === "tool_failed";
        // Read the field directly: this runs from the field's own change
        // handler, before the `barFocused` binding above has re-evaluated.
        const focused = root.fullRepresentationItem ? root.fullRepresentationItem.inputFocused : false;
        popup.visible = focused && somethingToShow;
    }

    /** Closes the popup on request (Escape, the close button): hides the
     *  conversation and drops the current file hits. The conversation itself
     *  is kept and reopens with Enter in the empty field. */
    function closePopup() {
        root.conversationOpen = false;
        root.popupToggled = false;
        searchDelay.stop();
        session.clearSearch();
        root.updatePopup();
    }

    function clearInput() {
        if (root.inputInPopup) {
            popup.clearInput();
        } else if (root.fullRepresentationItem) {
            root.fullRepresentationItem.clear();
        }
    }

    function handleEdited(text) {
        root.pendingQuery = text.trim();
        if (root.pendingQuery.length >= 2) {
            searchDelay.restart();
        } else {
            searchDelay.stop();
            session.clearSearch();
        }
    }

    function moveSelection(delta) {
        const count = session.hits.length;
        if (count === 0) {
            return;
        }
        popup.selectedIndex = Math.max(-1, Math.min(count - 1, popup.selectedIndex + delta));
    }

    function openHit(location) {
        session.openLocation(location);
        root.clearInput();
        root.popupToggled = false;
        root.updatePopup();
    }

    function handleAccepted(text) {
        if (popup.selectedIndex >= 0 && popup.selectedIndex < session.hits.length) {
            root.openHit(session.hits[popup.selectedIndex].location);
            return;
        }
        if (text.length === 0 && session.needsSetup) {
            root.openSettings();
            return;
        }
        if (text.length === 0) {
            root.conversationOpen = session.hasTranscript;
        } else if (session.ask(text)) {
            root.conversationOpen = true;
            root.clearInput();
        }
        root.updatePopup();
    }

    function focusBar() {
        root.wantsInput = true;
        // The panel window gains focus only after the status change above is
        // processed, so the field is focused on the next event loop turn.
        Qt.callLater(function() {
            if (root.fullRepresentationItem) {
                root.fullRepresentationItem.takeFocus();
            }
        });
    }

    Connections {
        target: Plasmoid
        function onActivated() {
            if (root.inputInPopup) {
                root.popupToggled = !popup.visible;
                root.updatePopup();
            } else {
                root.focusBar();
            }
        }
    }
}
