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
 * - Search-bar form: the panel field is a search, like the application
 *   launcher's. As the user types, after a short pause (`searchDelay`,
 *   `session.search`), what matches on this computer shows right above the
 *   bar (PanelResults.qml, which never takes the keyboard, so typing stays
 *   in the bar): installed applications, settings pages,
 *   quick answers, saved chats, then files, with an "Ask Happy Bot about …"
 *   row below. The top result is selected (`barSelectedIndex`); Down and Up
 *   move the selection, Down past the last result reaches the Ask row.
 *   Enter opens the selected result, and Enter typed before the results
 *   arrive waits for them (`acceptAfterSearch`), so a quick "minecraft" +
 *   Enter starts the launcher rather than asking. The assistant is asked
 *   only from the Ask row (clicked, or selected with Enter, as it is when
 *   nothing matched): the popup opens with the request (`askFromBar`).
 *   Enter on an empty bar, the logo or the widget shortcut opens the popup;
 *   a draft returns to the bar on click-away.
 * - The open assistant (popup or floating) shows the file finder, current
 *   chat or welcome screen, and typing there is a request: nothing is
 *   searched as the user types and Enter sends it to the assistant, which
 *   searches when the request needs it. Only the file finder ("Find a file"
 *   on the welcome screen, `session.findingFiles`, `searchable`) searches as
 *   the user types, the same search as the panel bar (applications,
 *   settings, answers, saved chats, files); there Down/Up move a
 *   selection, Tab completes the top result's name, Enter opens the
 *   selected result, and the Ask row below asks the assistant to find it. Leaving (Back,
 *   Escape on an empty field, closing, sending) ends it. Optional prefixes
 *   (barInput.js) say what Enter asks (`?` web, `>` a shell command). With
 *   no results, Up and Down recall earlier requests from this session.
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
 * in (`session.captureApplication`) so questions are about it; the panel's
 * icon, bar and logo note it as well. In the app,
 * Happy Bot opens right at the floating button, in the same view as the
 * popup; in a panel, in the bar or popup.
 * While the floating one is open it is the `surface` the keyboard handlers
 * work on (selection, Enter, putting text in the field). Opening from the
 * panel notes the application too: with the panel focused, the window the
 * user was in is the topmost one on the desktop (kwin_bridge's
 * CURRENT_WINDOW_JS), so "Help with …" works there as from the floating
 * button. The button's position is saved in
 * `floatingX`/`floatingY` when it is dragged.
 *
 * The floating button's right-click opens its own menu (settings, new
 * conversation, send feedback, quit the app), without "Remove from panel",
 * which there would remove the floating button along with the widget. Both
 * menus' "Send feedback…" opens `feedbackUrl` (metadata.json's
 * BugReportUrl) in the browser; nothing is sent from Happy Bot itself.
 * Settings: nearly all of Happy Bot's settings belong to the app. The
 * daemon keeps them (models, tools, behaviour, history, routines, and the
 * look and feel in `session.ui`), so the panel widget follows the app.
 * In the panel, "Configure Happy Bot…" (and every "open settings" in the
 * popup) opens the app's settings, starting the app if needed
 * (`openAppSettings`). That is Happy Bot's one settings dialog: even this
 * widget's icon-or-search-bar and bar width are set there (Appearance,
 * through the daemon's `/panel`); the widget's own Plasma page, reached only
 * from Plasma's panel edit mode, points there (contents/config/config.qml).
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
    property string pendingQuery: ""
    // Enter pressed while the search for this text was still running: acted on when it finishes.
    property string acceptAfterSearch: ""
    property bool acceptFromBar: false  // that Enter came from the panel bar (`barAccepted`)
    property string talkSource: ""  // where listening started: "bar" or "assistant" (`talk`)
    // The panel bar's results (PanelResults.qml): the selected one, and whether the bar has the
    // keyboard (kept a moment after it loses it, so a click on a result still lands).
    property int barSelectedIndex: -1
    property bool barFocused: false
    readonly property string barText: root.barMode && root.fullRepresentationItem
        ? String(root.fullRepresentationItem.text || "").trim() : ""
    // Requests sent from the bar in this session, oldest first, for Up/Down
    // recall; `recallIndex` is the one shown (equal to the length: none).
    property var sentRequests: []
    property int recallIndex: 0

    // plasmawindowed publishes this string as the tray's theme icon name.
    Plasmoid.icon: {
        if (session.ui.robot_mascot && iconActivity.trayPose) {
            return Plasmoid.pluginName + "-" + iconActivity.trayPose;
        }
        if (iconActivity.recording) {
            return "audio-input-microphone";
        }
        return root.standalone && session.ui.robot_mascot ? Plasmoid.pluginName : Look.assistantIcon(session.ui.robot_mascot);
    }
    Plasmoid.title: i18n("Happy Bot")
    Plasmoid.status: {
        if (wantsInput) {
            return PlasmaCore.Types.AcceptingInputStatus;
        }
        if (session.pendingApprovals > 0) {
            return PlasmaCore.Types.NeedsAttentionStatus;
        }
        return iconActivity.recording || session.busy || popup.visible || root.floatingOpen ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.PassiveStatus;
    }
    toolTipSubText: iconActivity.recording ? i18n("Recording microphone") : session.statusText
    activationTogglesExpanded: false
    preferredRepresentation: barMode ? fullRepresentation : compactRepresentation

    onBarModeChanged: {
        root.wantsInput = false;
        root.closePopup();
    }

    // Run as the Happy Bot app (happy-bot-app: plasmawindowed, which gives the "application" form
    // factor) rather than in a panel or on the desktop: then this is the floating Happy Bot only.
    readonly property bool standalone: Plasmoid.formFactor === PlasmaCore.Types.Application
    // Where "Send feedback…" goes: metadata.json's BugReportUrl, which Plasma's About page also shows.
    readonly property string feedbackUrl: Plasmoid.metaData.bugReportUrl || ""
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

    IconActivity { id: iconActivity }

    // A capture can be shorter than the normal status refresh. Both applet
    // instances wait independently, including while an assistant request runs.
    Timer {
        id: activityWait
        property string revision: ""
        interval: 0
        running: true
        onTriggered: session.request("GET", "/icon/activity?seen=" + revision, null, data => {
            iconActivity.apply(data);
            revision = data.revision;
            interval = 0;
            restart();
        }, () => {
            iconActivity.apply({});
            revision = "";
            interval = 5000;
            restart();
        })
    }

    AssistantSession {
        id: session
        configuredUrl: Plasmoid.configuration.daemonUrl || ""
        // The top result starts selected, so Enter opens it; with none, the Ask row is selected (-1).
        onHitsChanged: {
            popup.selectedIndex = session.hits.length > 0 ? 0 : -1;
            root.barSelectedIndex = popup.selectedIndex;
            if (root.floating) {
                root.floating.selectedIndex = popup.selectedIndex;
            }
        }
        onSearchingChanged: {
            if (!session.searching && root.acceptAfterSearch.length > 0) {
                const text = root.acceptAfterSearch;
                const fromBar = root.acceptFromBar;
                root.acceptAfterSearch = "";
                root.acceptFromBar = false;
                if (fromBar) {
                    root.barAccepted(text);
                } else {
                    root.handleAccepted(text);
                }
            }
        }
        // A "Help with …" screenshot briefly made the application active; take the keyboard back.
        onCapturingChanged: {
            if (!capturing) {
                root.surface.refocus();
            }
        }
    }

    Timer {
        id: searchDelay
        interval: 200  // ms of no typing before searching
        onTriggered: session.search(root.pendingQuery)
    }

    ResultsPopup {
        id: popup
        useRobotMascot: session.ui.robot_mascot
        holdOpen: session.capturing
        session: session
        widthInGridUnits: session.ui.popup_width
        heightInGridUnits: session.ui.popup_height
        visualParent: root
        location: Plasmoid.location
        onQueryEdited: text => root.handleEdited(text)
        onAccepted: text => root.handleAccepted(text)
        onAskRequested: text => root.askAssistant(text)
        onTalkRequested: root.talk("assistant")
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
            session.stopFindingFiles();
            root.cancelTalking();
            if (root.barMode && root.fullRepresentationItem) {
                root.fullRepresentationItem.setText(popup.inputText);
            }
            popup.clearInput();
        }
    }

    compactRepresentation: CompactRepresentation {
        status: session.status
        iconName: Plasmoid.icon
        busy: session.busy
        needsAttention: session.pendingApprovals > 0
        Accessible.description: iconActivity.recording ? i18n("Recording microphone") : ""
        open: popup.visible
        onClicked: {
            session.captureApplication();  // the application the user was in, as from the floating button
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
            activity: iconActivity
            busy: session.busy
            useRobotMascot: session.ui.robot_mascot
            holdOpen: session.capturing
            widthInGridUnits: session.ui.popup_width
            heightInGridUnits: session.ui.popup_height
            onClicked: root.openForApplication()
            onMenuRequested: floatingMenu.openRelative()
            onMoved: (x, y) => session.saveUi({ floating_x: x, floating_y: y })
            onQueryEdited: text => root.handleEdited(text)
            onAccepted: text => root.handleAccepted(text)
            onAskRequested: text => root.askAssistant(text)
            onTalkRequested: root.talk("assistant")
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
                session.stopFindingFiles();
                root.cancelTalking();
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
            session.captureApplication();
            if (session.pendingApprovals > 0) {
                root.openPopup();
            } else {
                root.focusBar();
            }
        }
        voiceEnabled: session.voiceEnabled
        listening: session.listening
        voiceProblem: session.voiceProblem
        onMicClicked: root.talk("bar")
        onAccepted: text => root.barAccepted(text)
        onTextEdited: text => root.barEdited(text)
        onSelectionMove: delta => root.moveBarSelection(delta)
        onDismissed: root.closePopup()
        onMenuRequested: contextMenu.openRelative()
        onIconClicked: {
            session.captureApplication();
            root.togglePopup();
        }
        onInputFocusedChanged: {
            if (inputFocused) {
                barBlur.stop();
                root.barFocused = true;
            } else {
                root.wantsInput = false;
                barBlur.restart();
            }
        }
    }

    Timer {
        id: barBlur
        interval: 300  // ms: a click on a result arrives after the bar has let go of the keyboard
        onTriggered: root.barFocused = false
    }

    // What matches the panel bar's text, right above the bar while the user types there.
    PanelResults {
        session: session
        visualParent: root.fullRepresentationItem
        location: Plasmoid.location
        visible: root.barMode && root.barFocused && root.barText.length > 0 && !popup.visible
            && (session.searching || session.searchedText.length > 0)
        query: root.barText
        selectedIndex: root.barSelectedIndex
        assistantIcon: Look.assistantIcon(session.ui.robot_mascot)
        useRobotMascot: session.ui.robot_mascot
        onResultActivated: hit => root.openBarHit(hit)
        onFileActionRequested: (hit, action) => {
            if (action === "ask") {
                session.clearSearch();
            }
            root.fileAction(hit, action);
        }
        onAskRequested: text => root.askFromBar(text)
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
            text: i18n("New conversation")
            icon: "document-new"
            onClicked: session.newChat()
        }

        PlasmaExtras.MenuItem {
            text: i18n("Send feedback…")
            icon: "tools-report-bug"
            visible: root.feedbackUrl.length > 0
            onClicked: Qt.openUrlExternally(root.feedbackUrl)
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
            text: i18n("Send feedback…")
            icon: "tools-report-bug"
            visible: root.feedbackUrl.length > 0
            onClicked: Qt.openUrlExternally(root.feedbackUrl)
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
            } else if (fresh && data.action === "talk") {
                // The "Talk to Happy Bot" shortcut: open here, listening (pressed again: stop and send).
                if (!session.listening) {
                    root.openForApplication();
                }
                root.talk("assistant");
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
                popup_height: [config.popupHeight, 26], floating_opacity: [config.floatingOpacity, 40],
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
        if (popup.visible) {
            return;
        }
        if (root.barMode && root.fullRepresentationItem) {
            const draft = root.fullRepresentationItem.text;
            root.fullRepresentationItem.setText("");
            popup.setInput(draft);
        }
        session.refreshHistory();
        session.refreshStatus();  // picks up AIs added in the settings since the last check
        popup.visible = true;
    }

    function closePopup() {
        session.stopFindingFiles();
        if (root.floating) {
            root.floating.close();
        }
        root.clearInput();
        popup.visible = false;
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
        } else if (!popup.visible && root.barMode && root.fullRepresentationItem) {
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
            session.refreshHistory();
            session.refreshStatus();
            root.floating.open();
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

    /** Whether typing `text` in the popup or the floating Happy Bot searches: only in the file finder. */
    function searchable(text) {
        return session.findingFiles;
    }

    /** The panel bar's text changed: search it after a pause, or clear the results. */
    function barEdited(text) {
        root.pendingQuery = String(text || "").trim();
        root.acceptAfterSearch = "";
        if (root.pendingQuery.length > 0) {
            searchDelay.restart();
        } else {
            searchDelay.stop();
            session.clearSearch();
        }
    }

    /** Enter in the panel bar: open the selected result, or ask from the Ask row (see the header). */
    function barAccepted(text) {
        if (text.length === 0) {
            if (session.needsSetup) {
                root.openSettings();
            } else {
                root.openPopup();
            }
            return;
        }
        if (searchDelay.running || session.searching || session.searchedText !== text) {
            searchDelay.stop();
            if (!session.searching || session.searchedText !== text) {
                session.search(text);
            }
            root.acceptAfterSearch = text;
            root.acceptFromBar = true;
            return;
        }
        if (root.barSelectedIndex >= 0 && root.barSelectedIndex < session.hits.length) {
            root.openBarHit(session.hits[root.barSelectedIndex]);
        } else {
            root.askFromBar(text);
        }
    }

    /** Down and Up in the panel bar: through its results and the Ask row; with none, earlier requests. */
    function moveBarSelection(delta) {
        const count = session.hits.length;
        if (count === 0 || root.barText.length === 0) {
            root.recall(delta);
            return;
        }
        const position = root.barSelectedIndex < 0 ? count : root.barSelectedIndex;
        const next = Math.max(0, Math.min(count, position + delta));
        root.barSelectedIndex = next === count ? -1 : next;
    }

    /** A result chosen from the panel bar's list. A saved chat opens in the popup; anything else just opens. */
    function openBarHit(hit) {
        if (hit.kind === "quick" && hit.action.type === "conversation") {
            session.activateQuick(hit);
            session.clearSearch();
            root.fullRepresentationItem.setText("");
            root.openPopup();
            return;
        }
        root.openHit(hit);
    }

    /** The microphone (in the panel bar, the popup or the floating Happy Bot, or the Talk shortcut):
     *  listen, then send what was said to the assistant at once, as the maintainer chose. From the
     *  bar it goes the way of the Ask row (the popup opens with the answer); elsewhere into the open
     *  view. Clicking it again while listening stops and sends what was said so far. */
    function talk(source) {
        if (!session.listening) {
            root.talkSource = source;
        }
        session.talk(function(text) {
            if (source === "bar") {
                root.askFromBar(text);
                return;
            }
            if (!root.floatingOpen && !popup.visible) {
                root.openPopup();
            }
            root.askAssistant(text);
        }, function(message, code) {});
    }

    /** Closing Happy Bot while it listens for it drops the recording; listening for the bar goes on. */
    function cancelTalking() {
        if (session.listening && root.talkSource === "assistant") {
            session.stopListening(true);
        }
    }

    /** The panel bar's Ask row: the popup opens and the assistant gets the text as a request. */
    function askFromBar(text) {
        searchDelay.stop();
        session.clearSearch();
        if (root.fullRepresentationItem) {
            root.fullRepresentationItem.setText("");
        }
        root.openPopup();
        root.askAssistant(text);
    }

    function handleEdited(text) {
        root.pendingQuery = String(text || "").trim();
        root.acceptAfterSearch = "";
        if (root.pendingQuery.length > 0 && root.searchable(root.pendingQuery)) {
            searchDelay.restart();
        } else {
            searchDelay.stop();
            session.clearSearch();
        }
    }

    /** Down and Up through the results in the order shown; past the last one is the Ask row (-1). */
    function moveSelection(delta) {
        const count = session.hits.length;
        if (count === 0) {
            root.recall(delta);
            return;
        }
        const position = root.surface.selectedIndex < 0 ? count : root.surface.selectedIndex;
        const next = Math.max(0, Math.min(count, position + delta));
        root.surface.selectedIndex = next === count ? -1 : next;
    }

    function openLocation(location) {
        session.openLocation(location);
        root.closePopup();
    }

    /** A file opens; a quick result does its action (an application starts, a window comes forward...).
     *  A saved conversation opens in Happy Bot, which stays open. */
    function openHit(hit) {
        if (hit.kind === "quick") {
            session.activateQuick(hit);
            if (hit.action.type === "conversation") {
                searchDelay.stop();
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
        // Enter before the results for this text are in: act once they are (onSearchingChanged).
        if (text.length > 0 && root.searchable(text)
                && (searchDelay.running || session.searching || session.searchedText !== text)) {
            searchDelay.stop();
            if (!session.searching || session.searchedText !== text) {
                session.search(text);
            }
            root.acceptAfterSearch = text;
            return;
        }
        root.acceptAfterSearch = "";
        if (root.surface.selectedIndex >= 0 && root.surface.selectedIndex < session.hits.length) {
            root.openHit(session.hits[root.surface.selectedIndex]);
            return;
        }
        root.askAssistant(text);
    }

    /** Sends `text` to the assistant (Enter with the Ask row selected or no results, or the Ask row clicked). */
    function askAssistant(text) {
        root.acceptAfterSearch = "";
        if (session.findingFiles && text.length > 0) {
            // No match chosen: the assistant searches harder (other words, the whole index).
            searchDelay.stop();
            session.stopFindingFiles();
            text = "Find the file: " + text;
        }
        if (text.length === 0 && session.needsSetup) {
            root.openSettings();
            return;
        }
        if (text.length > 0 && session.ask(BarInput.request(BarInput.parse(text)))) {
            root.sentRequests = root.sentRequests.concat([text]).slice(-50);
            root.recallIndex = root.sentRequests.length;
            searchDelay.stop();
            session.stopFindingFiles();
            root.clearInput();
        }
    }

    Connections {
        target: Plasmoid
        // The hotkey (the widget's global shortcut): Happy Bot for the application in use.
        function onActivated() {
            if (root.floatingOpen || (!root.floating && (popup.visible || Date.now() - popup.hiddenAt < 300))) {
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
                session.stopFindingFiles();
            }
        }
    }
}
