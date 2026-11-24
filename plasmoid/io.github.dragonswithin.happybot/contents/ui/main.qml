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
 * - What the panel shows (`barMode`). By default the assistant's icon
 *   (CompactRepresentation.qml), which opens the popup. With the
 *   `inputInPanel` setting on a horizontal panel, a search bar
 *   (PanelBar.qml) instead; vertical panels always get the icon.
 * - Icon form: the popup (ResultsPopup.qml) is where typing happens. A
 *   click on the icon, or the applet's activation shortcut, opens it with
 *   the cursor in its field; the same again, Escape on an empty field, the
 *   close button or a click anywhere else closes it. The panel itself never
 *   takes keyboard focus, so Plasma's panel focus indicator never appears.
 * - Search-bar form: typing happens in the panel, and the popup only shows
 *   results without taking focus (`updateBarPopup`). A panel accepts key
 *   input only while an applet reports AcceptingInputStatus, so
 *   `wantsInput` drives `Plasmoid.status`: it is set before the bar is
 *   focused (a click on it or the activation shortcut, `focusBar`) and
 *   cleared when the bar loses focus. While the bar has focus Plasma draws
 *   its blue panel focus indicator; the user accepted that by choosing this
 *   form. The popup is visible while the bar has focus and there is
 *   something to show (matches, a search problem, or a conversation opened
 *   by submitting a request or pressing Enter in the empty bar, or by
 *   clicking the logo at the bar's left end, which shows the current and
 *   saved conversations with nothing typed and closes them on a second
 *   click). Focusing the bar alone opens nothing, unless an action waits
 *   for approval.
 *   Leaving the bar hides the popup, closes the conversation view and keeps
 *   the typed text; Escape on an empty bar, or the close button, closes the
 *   conversation too.
 * - What the popup shows. Files and the conversation take turns (see
 *   ResultsView.qml): file matches while there are any for the typed text,
 *   otherwise the conversation when `conversationOpen`. Opening the popup
 *   returns to the current conversation, or shows the saved conversations
 *   if there are any, else shows only the field. Submitting a request clears the matches and shows
 *   the conversation; Enter in an empty field shows the previous one; an
 *   approval request clears the matches so its card is in front of the user.
 * - Typing. When live results are on (`instant_search`), text of at least
 *   `instant_min_chars` characters is sent to the instant file search after
 *   `instant_delay_ms` of no typing; these and `instant_results` are the
 *   shared look-and-feel settings (`session.ui`, the app's Appearance page). The
 *   same pause also fetches quick results (answers, windows, applications,
 *   settings pages, conversations), shown above the files; choosing one
 *   carries out its action (`openHit`). Optional prefixes (barInput.js) narrow
 *   what is searched (`/` files, `=` answers) or what Enter asks (`?` web,
 *   `>` a shell command). With no results, Up and Down recall earlier
 *   requests from this session; Tab completes the top result's name. Down/Up move a selection
 *   through the hits. Enter opens the selected hit; with no selection it
 *   sends the text to the assistant.
 *
 * Happy Bot also runs as an app of its own (`standalone`): `happy-bot-app`
 * starts this widget in Plasma's plasmawindowed, and the "Happy Bot" entry
 * in the application menu runs it. Then the widget hides plasmawindowed's
 * window and shows only the floating Happy Bot (FloatingButton.qml) over
 * other windows; launching it again or clicking its tray entry opens the
 * floating view (the second launch arrives as `/app/wait` from the
 * daemon). In a panel there is no floating button; the panel widget and
 * the app can run side by side.
 *
 * The floating Happy Bot and the hotkey (the widget's global shortcut)
 * both call `openForApplication`, which notes the application the user is
 * in (`session.captureApplication`) so questions are about it. In the app,
 * Happy Bot opens right at the floating button, in the same view as the
 * popup; in a panel, in the bar or popup.
 * While the floating one is open it is the `surface` the keyboard handlers
 * work on (selection, Enter, putting text in the field). Opening from the
 * panel clears the application note. The button's position is saved in
 * `floatingX`/`floatingY` when it is dragged.
 *
 * The floating button's right-click opens its own menu (settings, new
 * conversation, hide the floating button), without "Remove from panel",
 * which there would remove the floating button along with the widget.
 * Settings: nearly all of Happy Bot's settings belong to the app. The
 * daemon keeps them (models, tools, behaviour, history, routines, and the
 * look and feel in `session.ui`), so the panel widget follows the app.
 * In the panel, "Configure Happy Bot…" (and every "open settings" in the
 * popup) opens the app's settings, starting the app if needed
 * (`openAppSettings`); "Panel widget settings…" opens this widget's own:
 * search bar or icon, and the bar's width (contents/config/config.qml).
 *
 * A right-click on the icon or the bar opens the applet's own small menu
 * (settings, new conversation, remove).
 *
 * The daemon's address and token belong to DaemonClient.qml. The settings
 * dialog (contents/config/config.qml) holds appearance options and the
 * assistant's own setup; `openSettings` shows it, which is where a "no model
 * yet" message sends the user.
 */
PlasmoidItem {
    id: root

    readonly property bool barMode: Plasmoid.configuration.inputInPanel
        && Plasmoid.formFactor !== PlasmaCore.Types.Vertical
    property bool wantsInput: false
    property bool conversationOpen: false
    property string pendingQuery: ""
    property string pendingMode: "all"
    // Requests sent from the bar in this session, oldest first, for Up/Down
    // recall; `recallIndex` is the one shown (equal to the length: none).
    property var sentRequests: []
    property int recallIndex: 0

    // plasmawindowed publishes this string as the tray's theme icon name.
    Plasmoid.icon: root.standalone && session.ui.robot_mascot
        ? Plasmoid.pluginName : Look.assistantIcon(session.ui.robot_mascot)
    Plasmoid.title: i18n("Happy Bot")
    Plasmoid.status: {
        if (wantsInput) {
            return PlasmaCore.Types.AcceptingInputStatus;
        }
        if (session.pendingApprovals > 0) {
            return PlasmaCore.Types.NeedsAttentionStatus;
        }
        return session.busy || popup.visible || root.floatingOpen ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.PassiveStatus;
    }
    toolTipSubText: session.statusText
    activationTogglesExpanded: false
    preferredRepresentation: barMode ? fullRepresentation : compactRepresentation

    onBarModeChanged: {
        root.wantsInput = false;
        root.closePopup();
    }
    onConversationOpenChanged: root.updateBarPopup()

    // Run as the Happy Bot app (happy-bot-app: plasmawindowed, which gives the "application" form
    // factor) rather than in a panel or on the desktop: then this is the floating Happy Bot only.
    readonly property bool standalone: Plasmoid.formFactor === PlasmaCore.Types.Application
    // The app's host window (plasmawindowed's), hidden: the floating Happy Bot is the app's face.
    readonly property var hostWindow: standalone ? root.Window.window : null
    property bool hostWindowSeen: false
    // "Show yourself" requests seen from the daemon (`happy-bot app show`); -1 before the first answer.
    property int showRequests: -1

    // The floating Happy Bot in the app, and whether it is open. While it is open it is
    // where the user types, so the keyboard handlers below work on it instead of the panel popup.
    readonly property var floating: floatingLoader.item
    readonly property bool floatingOpen: floating !== null && floating.expanded
    readonly property var surface: floatingOpen ? floating : popup

    AssistantSession {
        id: session
        configuredUrl: Plasmoid.configuration.daemonUrl || ""
        searchLimit: session.ui.instant_results
        onHitsChanged: {
            popup.selectedIndex = -1;
            if (root.floating) {
                root.floating.selectedIndex = -1;
            }
            root.updateBarPopup();
        }
        onSearchErrorChanged: root.updateBarPopup()
    }

    Timer {
        id: searchDelay
        interval: session.ui.instant_delay_ms
        onTriggered: session.searchFiles(root.pendingQuery, root.pendingMode)
    }

    ResultsPopup {
        id: popup
        useRobotMascot: session.ui.robot_mascot
        session: session
        showConversation: root.conversationOpen
        takesFocus: !root.barMode
        barText: root.barMode && root.fullRepresentationItem ? root.fullRepresentationItem.text : ""
        widthInGridUnits: session.ui.popup_width
        heightInGridUnits: session.ui.popup_height
        visualParent: root
        location: Plasmoid.location
        onQueryEdited: text => root.handleEdited(text)
        onAccepted: text => root.handleAccepted(text)
        onSelectionMove: delta => root.moveSelection(delta)
        onCompleteRequested: root.completeFromTop()
        onHitActivated: location => root.openLocation(location)
        onResultActivated: hit => root.openHit(hit)
        onFileActionRequested: (hit, action) => root.fileAction(hit, action)
        onPanelPromptChosen: prompt => {
            root.setInput(prompt);
            root.focusBar();
        }
        onFilesDropped: paths => root.setInput(i18n("About %1: ", paths.join(", ")))
        onCloseRequested: root.closePopup()
        onSettingsRequested: root.openSettings()
        // In the search-bar form the popup also hides while the user is still
        // typing (nothing to show yet), so only the icon form resets here.
        onDismissed: {
            if (!root.barMode) {
                searchDelay.stop();
                session.clearSearch();
                popup.clearInput();
            }
        }
    }

    compactRepresentation: CompactRepresentation {
        status: session.status
        iconName: Plasmoid.icon
        busy: session.busy
        needsAttention: session.pendingApprovals > 0
        open: popup.visible
        onClicked: {
            session.forgetApplication();  // opened from the panel, not from an application
            root.togglePopup();
        }
        onMenuRequested: contextMenu.openRelative()
    }

    // The floating Happy Bot over other windows (FloatingButton.qml): the app's whole interface.
    // It opens into the same view as the popup, right where it is; no panel is needed.
    Loader {
        id: floatingLoader
        active: root.standalone
        sourceComponent: FloatingButton {
            session: session
            posX: session.ui.floating_x
            posY: session.ui.floating_y
            idleOpacity: session.ui.floating_opacity / 100
            iconSource: Plasmoid.icon
            busy: session.busy
            useRobotMascot: session.ui.robot_mascot
            showConversation: root.conversationOpen
            widthInGridUnits: session.ui.popup_width
            heightInGridUnits: session.ui.popup_height
            onClicked: root.openForApplication()
            onMenuRequested: floatingMenu.openRelative()
            onMoved: (x, y) => session.saveUi({ floating_x: x, floating_y: y })
            onQueryEdited: text => root.handleEdited(text)
            onAccepted: text => root.handleAccepted(text)
            onSelectionMove: delta => root.moveSelection(delta)
            onCompleteRequested: root.completeFromTop()
            onHitActivated: location => root.openLocation(location)
            onResultActivated: hit => root.openHit(hit)
            onFileActionRequested: (hit, action) => root.fileAction(hit, action)
            onFilesDropped: paths => root.setInput(i18n("About %1: ", paths.join(", ")))
            onCloseRequested: root.closePopup()
            onSettingsRequested: root.openSettings()
            onDismissed: {
                searchDelay.stop();
                session.clearSearch();
                clearInput();
            }
        }
    }

    // The search-bar form, shown inline in the panel when `barMode`. The
    // applet never expands into it as a popup (`activationTogglesExpanded`
    // is false), so in the icon form it is unused.
    fullRepresentation: PanelBar {
        busy: session.busy
        statusText: session.pendingApprovals > 0 ? i18n("Waiting for your approval — click here")
            : session.needsSetup && session.status !== "offline" ? i18n("Type here, or press Enter to set up")
            : session.statusText
        offline: session.status === "offline" || session.pendingApprovals > 0 || session.needsSetup
        iconName: Plasmoid.icon
        widthInGridUnits: Plasmoid.configuration.barWidth

        onFocusRequested: {
            session.forgetApplication();  // clicked in the panel, not opened from an application
            root.focusBar();
        }
        onQueryEdited: text => root.handleEdited(text)
        onAccepted: text => root.handleAccepted(text)
        onSelectionMove: delta => root.moveSelection(delta)
        onCompleteRequested: root.completeFromTop()
        onDismissed: root.closePopup()
        onMenuRequested: contextMenu.openRelative()
        onIconClicked: root.toggleConversationsFromBar()
        onInputFocusedChanged: {
            if (!inputFocused) {
                root.wantsInput = false;
                searchDelay.stop();
                session.clearSearch();
                // Clicking away also closes the conversation view, so focusing the
                // bar again to type does not bring it back (the logo does).
                root.conversationOpen = false;
            } else {
                if (session.pendingApprovals > 0) {
                    root.conversationOpen = true;
                }
                // Text kept from before the bar lost focus gets its matches back.
                if (text.length > 0) {
                    root.handleEdited(text);
                }
            }
            root.updateBarPopup();
        }
    }

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
            text: i18n("Panel widget settings…")
            icon: "configure"
            visible: !root.standalone
            onClicked: Plasmoid.internalAction("configure").trigger()
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

    // The floating button's own menu: no "Remove from panel" (it is not in a panel), and Quit ends the app.
    PlasmaExtras.Menu {
        id: floatingMenu
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
            text: i18n("Quit Happy Bot")
            icon: "application-exit"
            onClicked: Qt.quit()
        }
    }

    // The app: hide the host window when it appears; when it appears again (its tray entry was
    // clicked), hide it and open the floating Happy Bot instead.
    Connections {
        target: root.hostWindow
        function onVisibleChanged() {
            if (!root.hostWindow.visible) {
                return;
            }
            Qt.callLater(function() { root.hostWindow.visible = false; });
            if (root.hostWindowSeen) {
                root.openForApplication();
            }
            root.hostWindowSeen = true;
        }
    }

    onHostWindowChanged: {
        if (root.hostWindow && root.hostWindow.visible) {
            root.hostWindowSeen = true;
            Qt.callLater(function() { root.hostWindow.visible = false; });
        }
    }

    /** The app waits for "show yourself" (a second launch, or the hotkey) through the daemon. */
    function waitForShowRequest() {
        session.request("GET", "/app/wait?seen=" + root.showRequests, null, function(data) {
            // A second launch or the launch shortcut opens the floating Happy Bot, or closes it when open;
            // the panel widget asks for the settings. A request that started the app counts too.
            const fresh = root.showRequests >= 0 ? data.count > root.showRequests
                                                 : data.age >= 0 && data.age < 30;
            if (fresh && data.action === "settings") {
                root.openSettings();
            } else if (fresh && root.showRequests >= 0) {
                if (root.floatingOpen) {
                    root.closePopup();
                } else {
                    root.openForApplication();
                }
            }
            root.showRequests = data.count;
            root.waitForShowRequest();
        }, function(data) {
            showRetry.start();
        });
    }

    Timer {
        id: showRetry
        interval: 5000
        onTriggered: root.waitForShowRequest()
    }

    Component.onCompleted: {
        if (root.standalone) {
            root.waitForShowRequest();
        }
    }

    /** The panel widget: Happy Bot's settings belong to the app, so start it if needed and open them there. */
    function openAppSettings() {
        root.closePopup();
        session.request("POST", "/app", { start: true }, function(data) {
            session.request("POST", "/app/show", { action: "settings" }, function(data) {}, function(data) {});
        }, function(data) {});
    }

    // Before the look-and-feel settings moved to the daemon, each copy kept its own in Plasma. Each
    // copy hands over the values it had changed, once ("imported"), so nothing set earlier is lost.
    Connections {
        target: session
        function onUiLoadedChanged() {
            const copy = root.standalone ? "app" : "panel";
            const ui = session.ui;
            if (!session.uiLoaded || (ui.imported || []).indexOf(copy) >= 0) {
                return;
            }
            const config = Plasmoid.configuration;
            const old = {
                robot_mascot: [config.useRobotMascot, false], popup_width: [config.popupWidth, 30],
                popup_height: [config.popupHeight, 26], instant_search: [config.instantSearch, true],
                instant_min_chars: [config.instantMinChars, 2], instant_delay_ms: [config.instantDelayMs, 200],
                instant_results: [config.instantResults, 8], floating_opacity: [config.floatingOpacity, 40],
                floating_x: [config.floatingX, -1], floating_y: [config.floatingY, -1]
            };
            const changes = { imported: (ui.imported || []).concat([copy]) };
            for (const key in old) {
                if (old[key][0] !== undefined && old[key][0] !== old[key][1]) {
                    changes[key] = old[key][0];
                }
            }
            session.saveUi(changes);
        }
    }

    function openSettings() {
        if (!root.standalone) {
            root.openAppSettings();
            return;
        }
        root.closePopup();
        Plasmoid.internalAction("configure").trigger();
    }

    function openPopup() {
        // Reopening returns to the conversation in progress, if there is one.
        root.conversationOpen = session.hasTranscript || session.busy || session.pendingApprovals > 0
            || session.history.length > 0;
        session.refreshHistory();
        session.refreshStatus();  // picks up AIs added in the settings since the last check
        popup.visible = true;
    }

    function closePopup() {
        if (root.floating) {
            root.floating.close();
        }
        if (root.barMode) {
            root.conversationOpen = false;
            root.clearInput();
        }
        popup.visible = false;
    }

    /** Search-bar form: the popup shows while the bar has focus and has something to show. */
    function updateBarPopup() {
        if (!root.barMode) {
            return;
        }
        // Read the bar directly: this runs from the bar's own focus handler,
        // before any binding on its focus would have re-evaluated.
        const focused = root.fullRepresentationItem ? root.fullRepresentationItem.inputFocused : false;
        const somethingToShow = root.conversationOpen || session.hits.length > 0 || session.searchError.length > 0;
        popup.visible = focused && somethingToShow;
    }

    /** Search-bar form, the logo: show the conversation and saved ones with nothing typed, or close them. */
    function toggleConversationsFromBar() {
        if (popup.visible && root.conversationOpen) {
            root.closePopup();
            return;
        }
        root.conversationOpen = true;
        session.refreshHistory();
        session.refreshStatus();
        // The popup shows only while the bar has focus, so take it; focusing
        // runs updateBarPopup, which now has the conversation to show.
        root.focusBar();
        root.updateBarPopup();
    }

    function focusBar() {
        root.wantsInput = true;
        // The panel window gains focus only after the status change above is
        // processed, so the bar is focused on the next event loop turn.
        Qt.callLater(function() {
            if (root.fullRepresentationItem) {
                root.fullRepresentationItem.takeFocus();
            }
        });
    }

    /** Puts text in whichever field the user types in: the floating Happy Bot, the panel bar or the popup. */
    function setInput(text) {
        if (root.floatingOpen) {
            root.floating.setInput(text);
        } else if (root.barMode && root.fullRepresentationItem) {
            root.fullRepresentationItem.setText(text);
        } else {
            popup.setInput(text);
        }
    }

    function clearInput() {
        root.setInput("");
    }

    /** The floating button and the hotkey: open Happy Bot noting the application the user is in.
     *  With the floating button on, it opens right there; otherwise in the panel bar or popup. */
    function openForApplication() {
        session.captureApplication();
        if (root.floating) {
            popup.visible = false;
            root.conversationOpen = true;
            session.refreshHistory();
            session.refreshStatus();
            root.floating.open();
        } else if (root.barMode) {
            root.focusBar();
        } else if (!popup.visible) {
            root.openPopup();
        }
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
        if (session.ui.instant_search && root.pendingQuery.length >= session.ui.instant_min_chars) {
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
        root.surface.selectedIndex = Math.max(-1, Math.min(count - 1, root.surface.selectedIndex + delta));
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
                root.clearInput();
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
            root.setInput(i18n("About %1: ", hit.location));
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
        root.setInput(root.recallIndex < root.sentRequests.length ? root.sentRequests[root.recallIndex] : "");
    }

    /** Tab puts the top result's name in the field (an application, a setting, a file). */
    function completeFromTop() {
        if (session.hits.length > 0) {
            root.setInput(session.hits[0].title);
        }
    }

    function handleAccepted(text) {
        if (root.surface.selectedIndex >= 0 && root.surface.selectedIndex < session.hits.length) {
            root.openHit(session.hits[root.surface.selectedIndex]);
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
            root.clearInput();
        }
    }

    Connections {
        target: Plasmoid
        // The hotkey (the widget's global shortcut): Happy Bot for the application in use.
        function onActivated() {
            if (root.floatingOpen || (!root.floating && !root.barMode
                                      && (popup.visible || Date.now() - popup.hiddenAt < 300))) {
                root.closePopup();
            } else {
                root.openForApplication();
            }
        }
    }

    // An action that needs approval brings the conversation forward if the
    // popup is open, and the icon's ring asks for attention if it is not.
    Connections {
        target: session
        function onPendingApprovalsChanged() {
            if (session.pendingApprovals > 0 && (popup.visible || root.floatingOpen)) {
                searchDelay.stop();
                session.clearSearch();
                root.conversationOpen = true;
            }
        }
    }
}
