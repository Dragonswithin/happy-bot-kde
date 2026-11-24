/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick

import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.extras as PlasmaExtras
import org.kde.plasma.plasmoid

import "barInput.js" as BarInput

/**
 * Root of the panel applet. It composes the visual parts around one
 * AssistantSession and owns the rules that connect them:
 *
 * - What the panel shows: only the assistant's icon
 *   (CompactRepresentation.qml), which opens the popup.
 * - The popup (ResultsPopup.qml), where all typing happens. A click on the
 *   icon, or the applet's activation shortcut, opens it with the
 *   cursor in its field; the same again, Escape on an empty field, the close
 *   button or a click anywhere else closes it. The panel itself never takes
 *   keyboard focus, so Plasma's panel focus indicator never appears.
 * - What the popup shows. Files and the conversation take turns (see
 *   ResultsView.qml): file matches while there are any for the typed text,
 *   otherwise the conversation when `conversationOpen`. Opening the popup
 *   returns to the current conversation, or shows the saved conversations
 *   if there are any, else shows only the field. Submitting a request clears the matches and shows
 *   the conversation; Enter in an empty field shows the previous one; an
 *   approval request clears the matches so its card is in front of the user.
 * - Typing. When live results are on (`instantSearch`), text of at least
 *   `instantMinChars` characters is sent to the instant file search after
 *   `instantDelayMs` of no typing; these and `instantResults` are the
 *   applet's own settings (contents/config/main.xml, Search Bar page). The
 *   same pause also fetches quick results (answers, windows, applications,
 *   settings pages, conversations), shown above the files; choosing one
 *   carries out its action (`openHit`). Optional prefixes (barInput.js) narrow
 *   what is searched (`/` files, `=` answers) or what Enter asks (`?` web,
 *   `>` a shell command). With no results, Up and Down recall earlier
 *   requests from this session; Tab completes the top result's name. Down/Up move a selection
 *   through the hits. Enter opens the selected hit; with no selection it
 *   sends the text to the assistant.
 *
 * A right-click on the icon opens the applet's own small menu
 * (settings, new conversation, remove).
 *
 * The daemon's address and token belong to DaemonClient.qml. The settings
 * dialog (contents/config/config.qml) holds appearance options and the
 * assistant's own setup; `openSettings` shows it, which is where a "no model
 * yet" message sends the user.
 */
PlasmoidItem {
    id: root

    property bool conversationOpen: false
    property string pendingQuery: ""
    property string pendingMode: "all"
    // Requests sent from the bar in this session, oldest first, for Up/Down
    // recall; `recallIndex` is the one shown (equal to the length: none).
    property var sentRequests: []
    property int recallIndex: 0

    Plasmoid.icon: "tools-wizard"
    Plasmoid.title: i18n("Happy Bot")
    Plasmoid.status: {
        if (session.pendingApprovals > 0) {
            return PlasmaCore.Types.NeedsAttentionStatus;
        }
        return session.busy || popup.visible ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.PassiveStatus;
    }
    toolTipSubText: session.statusText
    activationTogglesExpanded: false
    preferredRepresentation: compactRepresentation

    AssistantSession {
        id: session
        configuredUrl: Plasmoid.configuration.daemonUrl || ""
        searchLimit: Plasmoid.configuration.instantResults
        onHitsChanged: popup.selectedIndex = -1
    }

    Timer {
        id: searchDelay
        interval: Plasmoid.configuration.instantDelayMs
        onTriggered: session.searchFiles(root.pendingQuery, root.pendingMode)
    }

    ResultsPopup {
        id: popup
        session: session
        showConversation: root.conversationOpen
        widthInGridUnits: Plasmoid.configuration.popupWidth
        heightInGridUnits: Plasmoid.configuration.popupHeight
        visualParent: root
        location: Plasmoid.location
        onQueryEdited: text => root.handleEdited(text)
        onAccepted: text => root.handleAccepted(text)
        onSelectionMove: delta => root.moveSelection(delta)
        onCompleteRequested: root.completeFromTop()
        onHitActivated: location => root.openLocation(location)
        onResultActivated: hit => root.openHit(hit)
        onFileActionRequested: (hit, action) => root.fileAction(hit, action)
        onFilesDropped: paths => popup.setInput(i18n("About %1: ", paths.join(", ")))
        onCloseRequested: root.closePopup()
        onSettingsRequested: root.openSettings()
        onDismissed: {
            searchDelay.stop();
            session.clearSearch();
            popup.clearInput();
        }
    }

    compactRepresentation: CompactRepresentation {
        status: session.status
        iconName: Plasmoid.icon
        busy: session.busy
        needsAttention: session.pendingApprovals > 0
        open: popup.visible
        onClicked: root.togglePopup()
        onMenuRequested: contextMenu.openRelative()
    }

    // Plasma only shows the icon form when the applet also has a full form,
    // even though this applet never expands into it: all of its interface
    // is in the icon and ResultsPopup.qml. This empty item satisfies that.
    fullRepresentation: Item {}

    // The applet's own right-click menu, with the entries a user needs from
    // Plasma's standard widget menu.
    PlasmaExtras.Menu {
        id: contextMenu
        visualParent: root

        PlasmaExtras.MenuItem {
            text: i18n("Configure Happy Bot…")
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

    function openPopup() {
        // Reopening returns to the conversation in progress, if there is one.
        root.conversationOpen = session.hasTranscript || session.busy || session.pendingApprovals > 0
            || session.history.length > 0;
        session.refreshHistory();
        popup.visible = true;
    }

    function closePopup() {
        popup.visible = false;
    }

    function togglePopup() {
        // A click on the icon first deactivates the open popup, which hides
        // it; that same click must not reopen it.
        if (popup.visible || Date.now() - popup.hiddenAt < 300) {
            root.closePopup();
        } else {
            root.openPopup();
        }
    }

    function handleEdited(text) {
        const parsed = BarInput.parse(text);
        root.pendingQuery = parsed.text;
        root.pendingMode = parsed.mode;
        if (Plasmoid.configuration.instantSearch
                && root.pendingQuery.length >= Plasmoid.configuration.instantMinChars) {
            searchDelay.restart();
        } else {
            searchDelay.stop();
            session.clearSearch();
        }
    }

    function moveSelection(delta) {
        const count = session.hits.length;
        if (count === 0) {
            root.recall(delta);
            return;
        }
        popup.selectedIndex = Math.max(-1, Math.min(count - 1, popup.selectedIndex + delta));
    }

    function openLocation(location) {
        session.openLocation(location);
        root.closePopup();
    }

    /** A file match opens; a quick result does its action. Opening a conversation keeps the popup. */
    function openHit(hit) {
        if (hit.kind === "quick") {
            session.activateQuick(hit);
            if (hit.action.type === "conversation") {
                root.conversationOpen = true;
                session.clearSearch();
                popup.clearInput();
                return;
            }
            root.closePopup();
            return;
        }
        root.openLocation(hit.location);
    }

    /** A file match's menu action: show it in the file manager, copy its path, or start a question about it. */
    function fileAction(hit, action) {
        if (action === "ask") {
            popup.setInput(i18n("About %1: ", hit.location));
            return;
        }
        session.activateQuick({ kind: "quick", title: hit.title, action: { type: action, target: hit.location } });
        if (action === "reveal") {
            root.closePopup();
        }
    }

    /** Up/Down with no results steps through the requests sent from the bar. */
    function recall(delta) {
        if (root.sentRequests.length === 0) {
            return;
        }
        root.recallIndex = Math.max(0, Math.min(root.sentRequests.length, root.recallIndex + delta));
        popup.setInput(root.recallIndex < root.sentRequests.length ? root.sentRequests[root.recallIndex] : "");
    }

    /** Tab puts the top result's name in the field (an application, a setting, a file). */
    function completeFromTop() {
        if (session.hits.length > 0) {
            popup.setInput(session.hits[0].title);
        }
    }

    function handleAccepted(text) {
        if (popup.selectedIndex >= 0 && popup.selectedIndex < session.hits.length) {
            root.openHit(session.hits[popup.selectedIndex]);
            return;
        }
        if (text.length === 0 && session.needsSetup) {
            root.openSettings();
            return;
        }
        if (text.length === 0) {
            root.conversationOpen = session.hasTranscript;
        } else if (session.ask(BarInput.request(BarInput.parse(text)))) {
            root.sentRequests = root.sentRequests.concat([text]).slice(-50);
            root.recallIndex = root.sentRequests.length;
            root.conversationOpen = true;
            searchDelay.stop();
            session.clearSearch();
            popup.clearInput();
        }
    }

    Connections {
        target: Plasmoid
        function onActivated() {
            root.togglePopup();
        }
    }

    // An action that needs approval brings the conversation forward if the
    // popup is open, and the icon's ring asks for attention if it is not.
    Connections {
        target: session
        function onPendingApprovalsChanged() {
            if (session.pendingApprovals > 0 && popup.visible) {
                searchDelay.stop();
                session.clearSearch();
                root.conversationOpen = true;
            }
        }
    }
}
