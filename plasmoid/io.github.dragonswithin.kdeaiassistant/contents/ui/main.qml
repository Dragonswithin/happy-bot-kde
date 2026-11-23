/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtCore as QtCore
import QtQuick

import org.kde.plasma.core as PlasmaCore
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
 * The daemon address defaults to the per-uid loopback port defined in
 * src/kde_ai_assistant/runtime_paths.py and can be overridden with the
 * `daemonUrl` setting in contents/config/main.xml. The token file path is
 * the one that module's `token_path` uses.
 */
PlasmoidItem {
    id: root

    // StandardPaths returns a file:// URL in QML; the scheme is stripped so
    // the value is a plain directory path such as /run/user/1000.
    readonly property string runtimeLocation: String(QtCore.StandardPaths.writableLocation(QtCore.StandardPaths.RuntimeLocation)).replace(/^file:\/\//, "")
    readonly property int sessionUid: {
        const match = runtimeLocation.match(/\/run\/user\/([0-9]+)/);
        return match ? parseInt(match[1]) : 1000;
    }
    readonly property int defaultDaemonPort: 19000 + Math.max(0, sessionUid - 1000)
    readonly property string configuredDaemonUrl: Plasmoid.configuration.daemonUrl || ""
    readonly property string daemonUrl: configuredDaemonUrl.length > 0
        ? configuredDaemonUrl
        : "http://127.0.0.1:" + defaultDaemonPort

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
        daemonUrl: root.daemonUrl
        tokenFile: root.runtimeLocation + "/kde-ai-assistant/token"
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
    }

    compactRepresentation: CompactRepresentation {
        status: session.status
        iconName: Plasmoid.icon
        onClicked: {
            root.popupToggled = !popup.visible;
            root.updatePopup();
        }
    }

    fullRepresentation: PanelBar {
        busy: session.busy
        statusText: session.pendingApprovals > 0 ? i18n("Waiting for your approval — click here") : session.statusText
        offline: session.status === "offline" || session.pendingApprovals > 0
        widthInGridUnits: Plasmoid.configuration.barWidth

        onFocusRequested: root.focusBar()
        onQueryEdited: text => root.handleEdited(text)
        onAccepted: text => root.handleAccepted(text)
        onSelectionMove: delta => root.moveSelection(delta)
        onDismissed: root.closePopup()
        onInputFocusedChanged: {
            if (!inputFocused) {
                root.wantsInput = false;
            } else if (session.pendingApprovals > 0) {
                root.conversationOpen = true;
            }
            root.updatePopup();
        }
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
