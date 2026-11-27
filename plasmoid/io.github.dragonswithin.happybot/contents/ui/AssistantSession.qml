/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick

/**
 * Non-visual owner of one conversation with the per-user daemon.
 *
 * Holds everything CompactRepresentation.qml and
 * ResultsPopup.qml display: the conversation `entries`, the busy flag, the
 * daemon status and the file finder's current matches. It talks to the
 * daemon (`/health`, `/search`, `/open`, `/ask`, `/cancel`, `/approve`)
 * through its own DaemonClient.qml, which owns the address and the bearer
 * token. main.qml creates exactly one instance and supplies `configuredUrl`.
 * `needsSetup` is true while the daemon reports that no AI model is chosen.
 * `models` is the user's AIs in order (`{name, online}`, from `/health`), and
 * `chatModel` the one picked for this chat in the popup's ModelPicker.qml
 * ("" = their usual order). It is sent with every request of the chat, the
 * daemon keeps it with the conversation, and opening a saved chat restores
 * it; a new chat starts on "", and a pick whose AI was removed falls back
 * to "".
 * `ui` is Happy Bot's look and feel (the daemon's `ui` settings,
 * src/happy_bot/ui_settings.py): the mascot, the popup's size, search while
 * typing, the floating Happy Bot's look and place. It comes with `/health`,
 * so the panel widget and the app always use the same values;
 * `saveUi(changes)` changes some of them (`POST /ui`). Until the first
 * answer it holds the defaults.
 * `helpWith` is the application the user was in (`{app, class, title, window}`,
 * from `/context/app`, empty when the user's privacy setting turned it off)
 * when Happy Bot was opened (`captureApplication`), or null. While set, it is sent with every request
 * as `about_window`, so the user never has to say which application they
 * mean; the welcome screen's help shortcut names it (AssistantWelcome.qml),
 * and it does not limit what they can ask about. `helpChat` is set when the
 * chat was started from that shortcut: its requests also carry
 * `full_context`, so the daemon adds the selected text, the window's controls
 * and its open file (src/happy_bot/app_context.py, which also decides which
 * AI may see any of it). Choosing that shortcut also calls `captureForHelp`,
 * which asks for a screenshot of the application (`POST /context/screenshot`)
 * to preview locally before the first question. Nothing is captured when Happy Bot opens. A new or
 * reopened chat clears `helpChat`. Every way of opening Happy Bot notes the
 * application (`captureApplication`), the panel included.
 *
 * Conversation: `ask` posts to `/ask`, which answers with a server-sent
 * event stream. XMLHttpRequest reports the growing response at readyState
 * LOADING; `consumeStream` parses the new part into events and `applyEvent`
 * turns them into `entries`. Each entry is `{kind, text, stage, callId,
 * approvalId, detail, canRemember, started, progress, card}` (`stage`, not `state`, because every QML
 * item already has a `state` property):
 *
 * - kind "user", "assistant" (Markdown, grows as text streams in), "notice"
 *   and "error" use `text`. When a request ends, every change the daemon
 *   reports as not done (failed, declined by the user, not run) becomes a
 *   "Not done: …" notice after the answer, followed by which model answered
 *   and the tokens (and cost, for a priced model) it used. A "notice" event
 *   (for example, the fallback model answered instead) is shown as is.
 * - kind "tool" is one tool call: `text` is its display name, `stage` is
 *   "running", "ok" or "failed", `callId` links the result to the call,
 *   `started` is when it began (ms since the epoch, for the elapsed-time
 *   display) and `progress` the latest status line it reported. `card` is
 *   the JSON of the card the daemon sent with a successful result (the
 *   weather, drawn by WeatherCard.qml), or "".
 * - kind "approval" is a tool call waiting for the user. The call's own
 *   "tool" entry turns into it in place, so one action is one row: `text`
 *   says what will run, `detail` why it needs approval, `approvalId` is what
 *   `answerApproval` sends back, `canRemember` whether "allow for this
 *   session" may be offered, and `stage` is "waiting". When the user allows
 *   it the row becomes a running "tool" again and finishes like any other
 *   step; any other answer leaves the card showing that outcome ("deny",
 *   "timeout", "cancelled"). `pendingApprovals` counts the waiting ones so
 *   the panel can draw attention.
 *
 * The daemon keeps the history; `conversationId` (from the stream's first
 * event) is sent with follow-ups and cleared by `newChat`.
 *
 * Saved conversations: `history` is the daemon's list of saved
 * conversations (`{id, title, updated, requests}`, newest first), refreshed
 * by `refreshHistory` after every request and when the popup opens.
 * `openConversation(id)` loads one and redraws it by replaying its saved
 * events through `applyEvent` (`replay`), so a reopened conversation looks
 * exactly as it did and the next request continues it. Anything that was
 * still waiting when it was saved is shown as not completed.
 * `pinConversation` pins one (listed first, never expired);
 * `deleteConversation` removes one; deleting the open one starts a new one. `cancel` aborts
 * the request, which makes the daemon stop the turn.
 *
 * Searching: `search(text)` looks up what is on this computer, with no
 * model. main.qml decides when (typing in the panel's search bar, or in
 * the popup's file finder). It asks the daemon for quick results (`/quick`: answers,
 * installed applications, settings pages, saved conversations;
 * `quickHits`) and for at most `searchLimit` file matches (`/search`;
 * `fileHits`) at once; `hits` is both, each kind together in the order
 * they are listed under their headings, applications first
 * (`Look.groupHits`). The popup has two finders, opened from its welcome
 * screen by `startFinding(kind)` until `stopFinding` (`finder` says which,
 * `finding` whether one is open): "Find a file" ("files") searches the
 * same way as the panel bar. "Search the web" ("web") opens with pinned and
 * frequent sites and submitted searches from /web/start. As you type it shows matching
 * bookmarks and visited websites (`/quick`, only those kinds) and web pages
 * from the user's web search tool (`/search/web`, from `WEB_MIN_CHARS`
 * characters; hits marked `source: "web"`) instead of files. When the
 * user's offline Wikipedia is set up (`wikipediaReady`, from `/health`), the
 * web finder also searches it (`/wikipedia/search`, `wikiHits`; hits marked
 * `source: "wikipedia"`, their `location` the article's path), and its
 * articles are listed under their own heading before the web's pages.
 * `openArticle(path)` gets the address of its own page (`/wikipedia/page`)
 * into `article` (`{title, path, url}` with `loading` and `error`; `text`
 * and `cut` once `loadArticleText` fetched the text view, where web pages
 * cannot be shown; `articleShown` follows links taken in the page), which
 * the view shows instead of the matches until `closeArticle`; leaving the finder
 * closes it too. `searching` is true until
 * both replies are in and `searchedText` is the text they are for, so Enter
 * typed before the results can wait for them. A quick hit has `kind`
 * "quick" and an `action`; `activateQuick` carries it out (an instant
 * command runs in the daemon), and also a file match's actions (show in the
 * file manager, copy the path, send it to the phone). `appInfo` and
 * `appAction` serve an application result's menu (`/quick/app`: update,
 * uninstall, start at login; src/happy_bot/app_actions.py).
 * Before anything is typed in the panel bar or a finder, `showRecent`
 * asks for the suggestions (`/quick/recent`: recent applications, files, settings, chats,
 * and websites when switched on; the web finder keeps only the websites); while they are shown `showingRecent` is
 * true and `hits` holds them instead of matches. Searching or `clearSearch`
 * ends that. Replies can
 * arrive out of order, so each request carries a sequence number and a
 * reply is applied only if it is the newest one sent. A file hit is
 * `{title, location, snippet, kind}`; `searchError`/`searchErrorCode` carry
 * the daemon's message and code ("not_configured", "tool_failed") when the
 * finder's last file search failed (outside the finder a failed file search
 * just shows no files).
 *
 * Fixing selected text: `startFixing` (the "Fix selected text" shortcut)
 * fetches the text the daemon noted when the shortcut was pressed
 * (`/selection`) into `fixing` (`{text, window, app, title, terminal}`;
 * `{loading: true}` until it arrives), which makes the open view show
 * SelectionFixCard.qml. `fixSelection(style, instruction)` asks for the
 * rewrite (`/selection/rewrite`: "fix", "shorter", "translate", "explain",
 * or the user's own instruction) into `fixResult`, with `fixReplaces`
 * (whether it can replace the selection), `fixModel`, `fixBusy` and
 * `fixProblem`. `replaceSelection` emits `selectionReplacing` (main.qml
 * closes Happy Bot so the application can take the paste) and asks the
 * daemon to paste the result over the selection (`/selection/replace`);
 * when that fails `fixing` is kept, `fixProblem` says why and
 * `selectionReplaceFailed` lets main.qml show it again. `stopFixing` ends
 * it, as do a new or reopened chat; replies that arrive after that are
 * ignored (`fixSequence`).
 *
 * System info: `showSystemInfo` (the start screen's optional button) sets
 * `showingSystem`, which makes the view show SystemInfoView.qml, until
 * `closeSystemInfo`, a finder, or a chat opened.
 *
 * Talking: `talk` asks the daemon to listen (`POST /voice/listen`, which
 * records until the user pauses and returns the text Whisper or another
 * speech service heard); `stopListening` ends it early. `voiceEnabled`
 * (from `/health`) says whether the microphone button shows; `listening`
 * whether it is recording now.
 *
 * Nothing here blocks: all requests are asynchronous on the GUI thread. A
 * failed or unreachable daemon sets `status` to "offline" and adds an error
 * entry instead of throwing. `status` is one of "starting", "idle",
 * "thinking" or "offline".
 */
Item {
    id: session

    property alias configuredUrl: client.configuredUrl
    property bool needsSetup: false
    property string status: "starting"
    property string statusText: i18n("Starting")
    property bool busy: false
    property string conversationId: ""
    property double conversationCreatedAt: 0
    property var models: []
    property string chatModel: ""
    property var helpWith: null
    property string helpWithIcon: ""  // the application's icon name, for the welcome screen only
    property bool helpChat: false  // this chat began with "Help with …": requests carry the full context
    property bool locatingApplication: false
    property int applicationLookup: 0
    property var helpWindow: null  // the target chosen on the tile, retained for follow-up questions
    property var helpDraft: null  // the capture in progress or the preview awaiting a question
    property bool includeHelpScreenshot: true
    property bool walkthrough: false
    property string helpAction: ""  // point/crop selection, applying an edit, or reading text
    property bool reviewingError: false
    property string helpErrorText: ""
    property string helpEditProblem: ""
    readonly property bool capturing: helpDraft?.loading === true
    readonly property bool helpPending: capturing || helpAction !== ""
    property var ui: ({
        robot_mascot: true, robot_style: "pip", mascot_animations: true, mascot_nudges: true, robot_sounds: false,
        popup_width: 30, popup_height: 26,
        floating_docked: false, floating_size: 100, floating_opacity: 40, floating_x: -1, floating_y: -1,
        imported: [], start_screen: ["files", "web", "help"]
    })
    property var nudges: []  // Active conditions from the shared icon activity stream.
    property bool showingTasks: false
    property bool showingSystem: false  // the start screen's System info view is shown (SystemInfoView.qml)
    property bool uiLoaded: false
    // Talking: the microphone button shows when the user switched voice on and set a speech service
    // (`voice` in /health); `listening` while the daemon records and turns speech into text.
    property bool voiceEnabled: false
    property bool listening: false
    property string voiceProblem: ""  // the last listening problem, shown in the field for a few seconds

    readonly property ListModel entries: ListModel {}
    property var history: []
    readonly property bool hasTranscript: entries.count > 0
    property int pendingApprovals: 0

    // "Fix selected text" (see the header): null when not fixing.
    property var fixing: null
    property string fixResult: ""
    property bool fixReplaces: false
    property string fixModel: ""
    property bool fixBusy: false
    property string fixProblem: ""
    property bool replacing: false
    property int fixSequence: 0
    signal selectionReplacing()
    signal selectionReplaceFailed()

    property int searchLimit: 20
    property string finder: ""  // the open finder: "files", "web", or "" for none
    property bool wikipediaReady: false  // offline Wikipedia is set up (from /health)
    property var article: null  // the Wikipedia article shown (see the header), or null
    readonly property bool finding: finder.length > 0
    readonly property int webMinChars: 3  // WEB_MIN_CHARS: shorter text is not sent to the web search
    property var quickHits: []
    property var fileHits: []
    property var wikiHits: []  // the web finder's offline Wikipedia articles
    property var recentHits: []
    property bool showingRecent: false
    property var webStartData: ({})
    property bool webStartLoading: false
    property string webStartProblem: ""
    property int webStartSequence: 0
    property var pendingSiteActions: []
    readonly property string webSiteSettings: JSON.stringify([ui.search_history, ui.web_pins, ui.web_hidden])
    onWebSiteSettingsChanged: {
        webStartData = {};
        if (finder === "web") loadWebStart();
    }
    readonly property var hits: Look.groupHits(showingRecent ? recentHits : quickHits.concat(wikiHits, fileHits))
    property bool searching: false
    property string searchedText: ""
    property string searchError: ""
    property string searchErrorCode: ""
    property int searchSequence: 0
    property double searchClearRevision: 0
    property double conversationClearRevision: 0
    signal searchReset()

    // The in-flight /ask request and how much of its response was parsed.
    property var activeStream: null
    property int streamOffset: 0
    property string streamBuffer: ""

    visible: false

    Component.onCompleted: {
        // A newly opened applet has no local results from before its own lifetime.
        session.searchClearRevision = Date.now() / 1000;
        session.conversationClearRevision = session.searchClearRevision;
        refreshStatus();
        refreshHistory();
    }

    Timer {
        interval: 12000
        repeat: true
        running: true
        onTriggered: session.refreshStatus()
    }

    function setStatus(status, summary) {
        session.status = status;
        session.statusText = summary;
    }

    function appendEntry(kind, text, stage, callId, detail, canRemember, approvalId) {
        session.entries.append({
            kind: kind, text: text || "", stage: stage || "", callId: callId || "",
            approvalId: approvalId || "", detail: detail || "", canRemember: canRemember === true,
            started: Date.now(), progress: "", card: ""
        });
    }

    /** Index of the newest entry whose `role` equals `value`, or -1. */
    function findEntry(role, value) {
        for (let index = session.entries.count - 1; index >= 0; index--) {
            if (value && session.entries.get(index)[role] === value) {
                return index;
            }
        }
        return -1;
    }

    /** Records a tool result. An approval card keeps the user's answer as its outcome. */
    function setEntryStage(callId, stage, card) {
        const index = findEntry("callId", callId);
        if (index >= 0 && session.entries.get(index).kind === "tool") {
            session.entries.setProperty(index, "stage", stage);
            if (card) {
                session.entries.setProperty(index, "card", JSON.stringify(card));
            }
        }
    }

    /** Sends the user's decision on a waiting action: "allow" or "deny". */
    function answerApproval(approvalId, decision, remember) {
        request("POST", "/approve", { id: approvalId, decision: decision, remember: remember === true },
            function(data) {}, function(data) {
                session.appendEntry("error", data.error || i18n("The answer could not be delivered"));
            });
    }

    DaemonClient {
        id: client
    }

    function request(method, path, payload, onSuccess, onFailure) {
        client.request(method, path, payload, onSuccess, onFailure);
    }

    function refreshStatus() {
        if (session.busy) {
            return;
        }
        request("GET", "/health", null, function(data) {
            session.needsSetup = !(data.setup && data.setup.model);
            session.models = data.models || [];
            if (data.ui && JSON.stringify(data.ui) !== JSON.stringify(session.ui)) {
                session.ui = data.ui;
            }
            session.uiLoaded = true;
            session.voiceEnabled = !!(data.voice && data.voice.enabled);
            session.wikipediaReady = data.wikipedia === true;
            if (session.chatModel && !session.models.some(item => item.name === session.chatModel)) {
                session.chatModel = "";
            }
            session.setStatus("idle", i18n("Ready"));
        }, function(data) {
            session.setStatus("offline", data.error || i18n("The assistant is not running"));
        });
    }

    function clearSearch() {
        session.searchReset();
        session.searchSequence += 1;
        session.wikiHits = [];
        session.showingRecent = false;
        session.recentHits = [];
        session.quickHits = [];
        session.fileHits = [];
        session.searching = false;
        session.searchedText = "";
        session.searchError = "";
        session.searchErrorCode = "";
    }

    /** A clear from Settings reaches every open app and panel through the activity stream. */
    function applyHistoryClears(data) {
        const search = Number(data.search_clear_revision || 0);
        const chats = Number(data.conversation_clear_revision || 0);
        const searchCleared = search > session.searchClearRevision;
        const chatsCleared = chats > session.conversationClearRevision;
        if (!searchCleared && !chatsCleared) return false;
        if (searchCleared) {
            session.searchClearRevision = search;
            session.webStartSequence++;
            session.webStartData = {};
            session.webStartLoading = false;
        }
        if (chatsCleared) session.conversationClearRevision = chats;
        session.clearSearch();  // the quick results and recent chips can both include chats
        if (chatsCleared && session.conversationCreatedAt <= chats) {
            // The daemon has already cancelled the forgotten turn. Detach its reply
            // before aborting so a final text delta cannot restore the transcript.
            const xhr = session.activeStream;
            session.activeStream = null;
            if (xhr) xhr.abort();
            session.busy = false;
            session.pendingApprovals = 0;
            session.streamBuffer = "";
            session.streamOffset = 0;
            session.resetTranscript();
            session.refreshStatus();
        }
        if (chatsCleared) {
            session.history = [];
            session.refreshHistory();
        }
        return true;
    }

    /** The empty bar's suggestions (`/quick/recent`); a search started meanwhile wins. */
    function showRecent() {
        if (session.finder === "web") {
            loadWebStart();
            return;
        }
        session.searchSequence += 1;
        const sequence = session.searchSequence;
        request("GET", "/quick/recent", null, function(data) {
            if (sequence === session.searchSequence) {
                session.recentHits = data.results || [];
                session.showingRecent = session.recentHits.length > 0;
            }
        }, function(data) {});
    }

    function removeRecent(hit) {
        const website = hit.action?.type === "visited";
        const target = website ? hit.action.target : hit.location;
        request("POST", "/quick/recent/remove", { kind: website ? "website" : "file", target }, () => {
            session.recentHits = session.recentHits.filter(item => website
                ? item.action?.type !== "visited" || item.action.target !== target : item.location !== target);
            session.quickHits = session.quickHits.filter(item => item.action?.type !== "visited" || item.action.target !== target);
            if (session.showingRecent)
                session.showRecent();
            else if (session.searchedText)
                session.search(session.searchedText);
        }, data => {
            session.searchError = data.error || i18n("Could not remove the recent entry.");
        });
    }

    function loadWebStart() {
        const sequence = ++session.webStartSequence;
        session.webStartLoading = true;
        session.webStartProblem = "";
        request("GET", "/web/start", null, function(data) {
            if (sequence !== session.webStartSequence) return;
            session.webStartData = data;
            session.webStartLoading = false;
        }, function(data) {
            if (sequence !== session.webStartSequence) return;
            session.webStartLoading = false;
            session.webStartProblem = data.error || i18n("Could not load your sites and searches.");
        });
    }

    function rememberWebSearch(query) {
        if (session.finder !== "web" || !query.trim()) return;
        request("POST", "/web/search/remember", {
            query: query.trim(), revision: session.webStartData.search_clear_revision ?? session.searchClearRevision
        }, function() {}, function() {});
    }

    function changeWebSite(location, action) {
        session.pendingSiteActions = session.pendingSiteActions.concat([{ url: location, action }]);
        if (session.pendingSiteActions.length === 1) saveNextSite();
    }

    function saveNextSite() {
        const revision = session.searchClearRevision;
        const settingsAtSave = session.webSiteSettings;
        function next() {
            session.pendingSiteActions = session.pendingSiteActions.slice(1);
            if (session.pendingSiteActions.length) saveNextSite();
        }
        request("POST", "/web/site", session.pendingSiteActions[0], function(data) {
            if (revision === session.searchClearRevision && settingsAtSave === session.webSiteSettings) {
                session.webStartSequence++;
                session.webStartLoading = false;
                session.webStartProblem = "";
                session.webStartData = data;
            } else if (session.finder === "web") {
                loadWebStart();
            }
            next();
        }, function(data) {
            session.webStartProblem = data.error || i18n("Could not save this site preference.");
            next();
        });
    }

    /** What an application result's menu offers (`{update, uninstall, autostart, ...}`), or null. */
    function appInfo(path, onInfo) {
        request("GET", "/quick/app?path=" + encodeURIComponent(path), null, onInfo, function(data) { onInfo(null); });
    }

    /** One of an application's menu actions: "update", "uninstall", "autostart_on" or "autostart_off". */
    function appAction(path, action) {
        request("POST", "/quick/app", { path: path, action: action }, function(data) {}, function(data) {
            session.appendEntry("error", data.error || i18n("That did not work"));
        });
    }

    /** Shows the text noted by the "Fix selected text" shortcut, with its rewrite buttons. */
    function startFixing() {
        stopFinding();
        session.fixSequence += 1;
        const sequence = session.fixSequence;
        session.fixing = { loading: true, text: "" };
        session.fixResult = "";
        session.fixProblem = "";
        session.fixBusy = false;
        request("GET", "/selection", null, function(data) {
            if (sequence === session.fixSequence) {
                session.fixing = data;
            }
        }, function(data) {
            if (sequence === session.fixSequence) {
                session.fixing = { text: "" };
                session.fixProblem = data.error || i18n("The selected text could not be read.");
            }
        });
    }

    /** Asks an AI to rewrite the noted text: `style` is "fix", "shorter", "translate" or "explain", or
     *  `instruction` is what the user typed. */
    function fixSelection(style, instruction) {
        if (!session.fixing || !session.fixing.text || session.fixBusy) {
            return;
        }
        const sequence = session.fixSequence;
        session.fixBusy = true;
        session.fixProblem = "";
        request("POST", "/selection/rewrite", { text: session.fixing.text, style: style || "",
                                                instruction: instruction || "" }, function(data) {
            if (sequence === session.fixSequence) {
                session.fixBusy = false;
                session.fixResult = data.text || "";
                session.fixReplaces = data.replaces === true;
                session.fixModel = data.model || "";
            }
        }, function(data) {
            if (sequence === session.fixSequence) {
                session.fixBusy = false;
                session.fixProblem = data.error || i18n("No AI could do it.");
            }
        });
    }

    /** Pastes `fixResult` over the selection in its application (see the header). */
    function replaceSelection() {
        if (!session.fixing || !session.fixResult || session.replacing) {
            return;
        }
        const sequence = session.fixSequence;
        session.replacing = true;
        session.fixProblem = "";
        session.selectionReplacing();
        request("POST", "/selection/replace", { window: session.fixing.window || "", text: session.fixResult },
            function(data) {
                session.replacing = false;
                if (sequence === session.fixSequence) {
                    stopFixing();
                }
            }, function(data) {
                session.replacing = false;
                if (sequence === session.fixSequence) {
                    session.fixProblem = data.error || i18n("The text could not be put back.");
                    session.selectionReplaceFailed();
                }
            });
    }

    function stopFixing() {
        session.fixSequence += 1;
        session.fixing = null;
        session.fixResult = "";
        session.fixReplaces = false;
        session.fixModel = "";
        session.fixBusy = false;
        session.fixProblem = "";
    }

    /** Opens a finder ("files" or "web"): typing now searches there, until `stopFinding`; until then,
     *  recent items. */
    function startFinding(kind) {
        clearSearch();
        session.finder = kind;
        if (kind === "web") session.webStartData = {};
        showRecent();
    }

    /** The start screen's "System info": live readings and programs, until `closeSystemInfo`. */
    function showSystemInfo() {
        stopFinding();
        session.showingSystem = true;
    }

    function showTasks() {
        stopFinding();
        session.showingTasks = true;
    }

    function closeSystemInfo() {
        session.showingSystem = false;
    }

    function stopFinding() {
        session.showingTasks = false;
        session.showingSystem = false;
        session.finder = "";
        session.article = null;
        clearSearch();
    }

    /** Shows the offline Wikipedia article at `path` (a hit's location, or a link in another article): the
     *  address of its own page (`/wikipedia/page`), which ArticleWebView.qml loads. */
    function openArticle(path, title) {
        const wanted = decodeURIComponent(String(path || "")).replace(/ /g, "_");
        session.article = { loading: true, title: title || wanted.replace(/_/g, " "), path: wanted, url: "", text: "",
                            cut: false, error: "" };
        request("GET", "/wikipedia/page?path=" + encodeURIComponent(wanted), null, function(data) {
            if (session.article && session.article.path === wanted) {
                session.article = Object.assign({}, session.article, { loading: false, url: data.url });
            }
        }, function(data) {
            if (session.article && session.article.path === wanted) {
                session.article = Object.assign({}, session.article, { loading: false,
                                                 error: data.error || i18n("The article could not be read.") });
            }
        });
    }

    /** The article's page followed a link: the header shows the article now in view. */
    function articleShown(title, path) {
        if (session.article && (session.article.title !== title || session.article.path !== path)) {
            session.article = Object.assign({}, session.article, { title: title, path: path });
        }
    }

    /** Where web pages cannot be shown: the article as light Markdown (`/wikipedia/article`). */
    function loadArticleText() {
        if (!session.article) {
            return;
        }
        const wanted = session.article.path;
        session.article = Object.assign({}, session.article, { loading: true });
        request("GET", "/wikipedia/article?path=" + encodeURIComponent(wanted), null, function(data) {
            if (session.article && session.article.path === wanted) {
                session.article = Object.assign({}, session.article, { loading: false, title: data.title,
                                                 text: data.text, cut: data.cut, error: "" });
            }
        }, function(data) {
            if (session.article && session.article.path === wanted) {
                session.article = Object.assign({}, session.article, { loading: false,
                                                 error: data.error || i18n("The article could not be read.") });
            }
        });
    }

    function closeArticle() {
        session.article = null;
    }

    /** Whether a hit belongs in the web finder: a bookmark, a visited website or a web page. */
    function webHit(hit) {
        return hit.source === "web" || (hit.kind === "quick" && ["bookmark", "visited"].indexOf(hit.action.type) >= 0);
    }

    /** Looks up `text`: quick results and files (the panel bar, "Find a file"), or in the web finder
     *  bookmarks, visited websites and web pages. */
    function search(text) {
        const query = (text || "").trim();
        if (query.length === 0) {
            clearSearch();
            return;
        }
        session.searchSequence += 1;
        session.showingRecent = false;
        const sequence = session.searchSequence;
        const inFinder = session.finding;
        const web = session.finder === "web";
        // The web finder also looks in the offline Wikipedia, whose articles are listed before the web's pages.
        const wiki = web && session.wikipediaReady && query.length >= session.webMinChars;
        let pending = wiki ? 3 : 2;
        session.searchedText = query;
        session.searching = true;
        session.wikiHits = [];
        function finished() {
            pending -= 1;
            if (pending === 0 && sequence === session.searchSequence) {
                session.searching = false;
            }
        }
        request("GET", "/quick?q=" + encodeURIComponent(query), null, function(data) {
            if (sequence === session.searchSequence) {
                session.quickHits = (data.results || []).filter(hit => !web || session.webHit(hit));
            }
            finished();
        }, function(data) {
            if (sequence === session.searchSequence) {
                session.quickHits = [];
            }
            finished();
        });
        if (wiki) {
            // A Wikipedia problem shows nothing here; the web's results (or problem) still show.
            request("GET", "/wikipedia/search?q=" + encodeURIComponent(query), null, function(data) {
                if (sequence === session.searchSequence) {
                    session.wikiHits = data.hits || [];
                }
                finished();
            }, function(data) {
                finished();
            });
        }
        if (web && query.length < session.webMinChars) {
            session.fileHits = [];
            finished();
            return;
        }
        const path = web ? "/search/web?q=" : "/search?limit=" + session.searchLimit + "&q=";
        request("GET", path + encodeURIComponent(query), null, function(data) {
            if (sequence === session.searchSequence) {
                session.searchError = "";
                session.searchErrorCode = "";
                session.fileHits = data.hits || [];
            }
            finished();
        }, function(data) {
            if (sequence === session.searchSequence) {
                session.fileHits = [];
                session.searchError = inFinder ? data.error || i18n("Search failed") : "";
                session.searchErrorCode = inFinder ? data.code || "tool_failed" : "";
            }
            finished();
        });
    }

    /** Listens until the user pauses (`POST /voice/listen`) and calls `onText` with what was said;
     *  while listening, it stops instead and what was said so far is sent (see voice.py). Problems
     *  ("did not hear anything", the service failing) come back through `onProblem`. */
    function talk(onText, onProblem) {
        if (session.listening) {
            stopListening(false);
            return;
        }
        session.listening = true;
        request("POST", "/voice/listen", {}, function(data) {
            session.listening = false;
            if (data.text) {
                onText(data.text);
            }
        }, function(data) {
            session.listening = false;
            session.voiceProblem = data.error || i18n("Happy Bot could not listen.");
            voiceProblemShown.restart();
            onProblem(session.voiceProblem, data.code || "");
        });
    }

    Timer {
        id: voiceProblemShown
        interval: 5000
        onTriggered: session.voiceProblem = ""
    }

    /** Ends listening now; `discard` drops what was said instead of sending it. */
    function stopListening(discard) {
        request("POST", "/voice/stop", { discard: discard === true }, function(data) {}, function(data) {});
    }

    /** Carries out an action (`{type, target}`) through the daemon's `/quick/activate`, such as a file match's
     *  "show in the file manager" or "copy path"; a conversation is opened here instead. A failure becomes
     *  an error entry, and `onFailure` (optional) is called after it. */
    function activateQuick(hit, onFailure) {
        if (hit.action.type === "conversation") {
            openConversation(hit.action.target);
            return;
        }
        request("POST", "/quick/activate", { action: hit.action }, function(data) {}, function(data) {
            session.appendEntry("error", data.error || i18n("Could not open %1", hit.title));
            if (onFailure) {
                onFailure();
            }
        });
    }

    function openLocation(location) {
        request("POST", "/open", { location: location }, function(data) {}, function(data) {
            session.appendEntry("error", data.error || i18n("Could not open %1", location));
        });
    }

    function refreshHistory() {
        const revision = session.conversationClearRevision;
        request("GET", "/conversations", null, function(data) {
            if (session.conversationClearRevision === revision)
                session.history = data.conversations || [];
        }, function(data) {});
    }

    /** Redraws a saved conversation from its events, without network or side effects. */
    function replay(events) {
        session.entries.clear();
        events.forEach(event => applyEvent(event));
        for (let index = 0; index < session.entries.count; index++) {
            const stage = session.entries.get(index).stage;
            if (stage === "running") {
                session.entries.setProperty(index, "stage", "failed");
            } else if (stage === "waiting") {
                session.entries.setProperty(index, "stage", "cancelled");
            }
        }
        session.pendingApprovals = 0;
        setStatus("idle", i18n("Ready"));
    }

    /** Shows the chat `conversationId` (its saved events, replayed), leaving a finder, an article or fixing text
     *  first, so a chat picked in the sidebar during a search comes to the front; the open chat just shows again. */
    function openConversation(conversationId) {
        dismissHelpDraft();
        stopFixing();
        stopFinding();
        if (session.busy || conversationId === session.conversationId) {
            return;
        }
        const revision = session.conversationClearRevision;
        request("GET", "/conversation?id=" + encodeURIComponent(conversationId), null, function(data) {
            if (session.conversationClearRevision !== revision && !(data.created > session.conversationClearRevision)) return;
            session.conversationId = data.id;
            session.conversationCreatedAt = Number(data.created || 0);
            session.helpChat = false;
            session.walkthrough = false;
            session.helpWindow = null;
            session.chatModel = session.models.some(item => item.name === data.model) ? data.model : "";
            session.replay(data.events || []);
        }, function(data) {
            if (session.conversationClearRevision !== revision) return;
            session.appendEntry("error", data.error || i18n("That conversation could not be opened"));
            session.refreshHistory();
        });
    }

    function deleteConversation(conversationId) {
        request("POST", "/conversations/delete", { id: conversationId }, function(data) {
            if (conversationId === session.conversationId) {
                session.newChat();
            }
            session.refreshHistory();
        }, function(data) {
            session.refreshHistory();
        });
    }

    /** Changes some of the shared look-and-feel settings; `then(ui)` gets them all back. */
    function saveUi(changes, then) {
        request("POST", "/ui", { changes: changes }, function(data) {
            session.ui = data.ui;
            if (then) {
                then(data.ui);
            }
        }, function(data) {});
    }

    /** Notes the application the user is in, for the next requests; called before the popup opens. */
    function captureApplication() {
        const lookup = ++session.applicationLookup;
        session.locatingApplication = true;
        request("GET", "/context/app", null, function(data) {
            if (lookup !== session.applicationLookup) return;
            session.helpWith = data.app || data.title
                ? { app: data.app, "class": data["class"], title: data.title, window: data.window || "" } : null;
            session.helpWithIcon = session.helpWith ? data.icon || "" : "";
            session.locatingApplication = false;
        }, function(data) {
            if (lookup !== session.applicationLookup) return;
            session.helpWith = null;
            session.helpWithIcon = "";
            session.locatingApplication = false;
        });
    }

    /** Open Help immediately. Ignore a late reply if the user already left this draft. */
    function captureForHelp() {
        if (session.capturing || session.busy) return;
        if (!session.helpChat || (session.helpWindow?.["class"]
                && session.helpWindow["class"] === session.helpWith?.["class"])) {
            session.helpWindow = session.helpWith;
        }
        if (!session.helpDraft) session.includeHelpScreenshot = true;
        session.helpChat = true;
        resetHelpEditor();
        session.helpDraft = { loading: true };
        const draft = session.helpDraft;
        const target = session.helpWindow;
        function finish(data) {
            if (session.helpDraft !== draft) return;
            session.helpDraft = {
                url: data.url || "", id: data.id || "", models: data.models || [], textModels: data.text_models || [],
                problem: data.url ? "" : data.reason === "disabled"
                    ? i18n("Screenshots are turned off in Behaviour settings. You can still ask a question.")
                    : i18n("Couldn’t capture the screenshot. You can still describe what you see.")
            };
        }
        request("POST", "/context/screenshot", { window: target?.window || "", desktop: !target, preview: true },
                finish, finish);
    }

    function resetHelpEditor() {
        session.helpAction = "";
        session.reviewingError = false;
        session.helpErrorText = "";
        session.helpEditProblem = "";
    }

    function editHelp(action, coordinates) {
        const draft = session.helpDraft;
        if (!draft?.id || session.helpAction === "applying" || session.helpAction === "reading") return;
        const reading = action === "read";
        session.helpAction = reading ? "reading" : "applying";
        session.helpEditProblem = "";
        if (reading) session.reviewingError = true;
        request("POST", "/context/screenshot/edit", { id: draft.id, action, coordinates },
            function(data) {
                if (session.helpDraft !== draft) return;
                session.helpAction = "";
                if (reading) {
                    session.helpErrorText = data.text || "";
                } else {
                    session.resetHelpEditor();
                    session.helpDraft = Object.assign({}, draft, { id: data.id, url: data.url, previous: draft,
                        cropped: draft.cropped || action === "crop" });
                }
            }, function(data) {
                if (session.helpDraft !== draft) return;
                session.helpAction = "";
                session.helpEditProblem = data.error || i18n("Couldn’t update the screenshot.");
            });
    }

    function dismissHelpDraft() {
        if (!session.helpDraft) return;
        session.helpDraft = null;
        resetHelpEditor();
        if (!session.hasTranscript) {
            session.helpWindow = null;
            session.helpChat = false;
            session.walkthrough = false;
        }
    }

    function newChat() {
        stopFixing();
        session.showingSystem = false;
        session.showingTasks = false;
        if (session.busy) {
            cancel();
        }
        resetTranscript();
        refreshStatus();
    }

    function resetTranscript() {
        session.conversationId = "";
        session.conversationCreatedAt = 0;
        session.chatModel = "";
        session.helpDraft = null;
        session.helpWindow = null;
        session.helpChat = false;
        session.walkthrough = false;
        resetHelpEditor();
        session.entries.clear();
    }

    /** Sends one request to the assistant. Returns false if it was not sent. */
    function ask(message) {
        let text = (message || "").trim();
        if (!text || session.busy || session.helpPending) {
            return false;
        }
        // With capture off, the user can still type an error message themselves.
        if (session.reviewingError && !session.helpDraft?.id && session.helpErrorText.trim())
            text += "\n\n" + session.helpErrorText.trim();
        session.showingTasks = false;
        session.showingSystem = false;  // the answer must show, not System info
        session.busy = true;
        if (!session.conversationId) session.conversationCreatedAt = Date.now() / 1000;
        setStatus("thinking", i18n("Thinking"));
        appendEntry("user", text);
        const body = { message: text, conversation_id: session.conversationId, model: session.chatModel,
                       buttons: true, about_window: session.helpChat ? session.helpWindow : session.helpWith };
        if (session.helpChat) {
            body.full_context = true;
            body.include_screenshot = !!session.helpDraft?.id && session.includeHelpScreenshot;
            body.screenshot_id = body.include_screenshot ? session.helpDraft.id : "";
            body.cropped_screenshot = session.helpDraft?.cropped === true;
            body.walkthrough = session.walkthrough;
            if (session.reviewingError && session.helpDraft?.id) body.help_error_text = session.helpErrorText.trim();
        }
        session.helpDraft = null;
        resetHelpEditor();
        const xhr = new XMLHttpRequest();
        session.activeStream = xhr;
        client.withToken(() => {
            if (session.activeStream === xhr) startStream(body, true, xhr);
        });
        return true;
    }

    function startStream(body, mayReload, xhr) {
        session.activeStream = xhr;
        session.streamOffset = 0;
        session.streamBuffer = "";
        xhr.open("POST", client.daemonUrl + "/ask");
        xhr.setRequestHeader("Content-Type", "application/json");
        xhr.setRequestHeader("Authorization", "Bearer " + client.token);
        xhr.onreadystatechange = function() {
            if (session.activeStream !== xhr) {
                return;
            }
            if (xhr.readyState === XMLHttpRequest.LOADING && xhr.status === 200) {
                session.consumeStream(xhr);
            } else if (xhr.readyState === XMLHttpRequest.DONE) {
                if (xhr.status === 401 && mayReload) {
                    client.loadToken(() => {
                        if (session.activeStream === xhr) session.startStream(body, false, new XMLHttpRequest());
                    });
                    return;
                }
                if (xhr.status === 200) {
                    session.consumeStream(xhr);
                } else if (xhr.status === 0) {
                    session.appendEntry("error", i18n("The assistant is not running"));
                } else {
                    session.appendEntry("error", i18n("The assistant could not take the request (%1)", xhr.status));
                }
                session.finishStream();
            }
        };
        xhr.send(JSON.stringify(body));
    }

    function consumeStream(xhr) {
        const body = xhr.responseText;
        session.streamBuffer += body.substring(session.streamOffset);
        session.streamOffset = body.length;
        let boundary = session.streamBuffer.indexOf("\n\n");
        while (boundary !== -1) {
            const block = session.streamBuffer.substring(0, boundary);
            session.streamBuffer = session.streamBuffer.substring(boundary + 2);
            if (block.startsWith("data:")) {
                try {
                    applyEvent(JSON.parse(block.substring(5)));
                } catch (error) {
                    // An unparsable block is skipped; the stream continues.
                }
            }
            boundary = session.streamBuffer.indexOf("\n\n");
        }
    }

    function finishStream() {
        session.activeStream = null;
        session.busy = false;
        session.pendingApprovals = 0;
        for (let index = 0; index < session.entries.count; index++) {
            const stage = session.entries.get(index).stage;
            if (stage === "running") {
                session.entries.setProperty(index, "stage", "failed");
            } else if (stage === "waiting") {
                session.entries.setProperty(index, "stage", "cancelled");
            }
        }
        refreshStatus();
        refreshHistory();
    }

    function toolLabel(name) {
        return name.replace("__", ": ").replace(/_/g, " ");
    }

    function applyEvent(event) {
        const last = session.entries.count - 1;
        switch (event.type) {
        case "user":
            appendEntry("user", event.text);
            break;
        case "start":
            session.conversationId = event.conversation_id;
            session.conversationCreatedAt = Number(event.created || session.conversationCreatedAt);
            (event.warnings || []).forEach(warning => session.appendEntry("notice", warning));
            break;
        case "thinking":
            setStatus("thinking", i18n("Thinking"));
            break;
        case "text_delta":
            setStatus("thinking", i18n("Answering"));
            if (last >= 0 && session.entries.get(last).kind === "assistant") {
                session.entries.setProperty(last, "text", session.entries.get(last).text + event.text);
            } else {
                appendEntry("assistant", event.text);
            }
            break;
        case "tool_call":
            setStatus("thinking", i18n("Using %1", toolLabel(event.name)));
            appendEntry("tool", event.summary && event.summary !== event.name
                ? event.summary : toolLabel(event.name), "running", event.id);
            break;
        case "tool_progress": {
            const step = findEntry("callId", event.id);
            if (step >= 0) {
                session.entries.setProperty(step, "progress", event.text || "");
            }
            break;
        }
        case "tool_result":
            setEntryStage(event.id, event.ok ? "ok" : "failed", event.card || null);
            break;
        case "approval_required": {
            setStatus("thinking", i18n("Waiting for your approval"));
            session.pendingApprovals += 1;
            const step = findEntry("callId", event.call_id);
            if (step >= 0) {
                session.entries.set(step, {
                    kind: "approval", text: event.summary, stage: "waiting", approvalId: event.id,
                    detail: event.detail || "", canRemember: event.can_remember === true
                });
            } else {
                appendEntry("approval", event.summary, "waiting", event.call_id, event.detail, event.can_remember, event.id);
            }
            break;
        }
        case "approval_resolved": {
            session.pendingApprovals = Math.max(0, session.pendingApprovals - 1);
            const card = findEntry("approvalId", event.id);
            if (card >= 0) {
                if (event.decision === "allow") {
                    session.entries.set(card, { kind: "tool", stage: "running", started: Date.now(), progress: "" });
                } else {
                    session.entries.setProperty(card, "stage", event.decision);
                }
            }
            setStatus("thinking", i18n("Working"));
            break;
        }
        case "done": {
            // The daemon's record of what was not done, shown after the
            // answer so it cannot be talked over by the model's own account.
            const reasons = { failed: i18n("failed"), declined: i18n("you declined"), not_run: i18n("not run") };
            (event.actions || []).filter(action => action.outcome !== "done").forEach(action =>
                appendEntry("notice", i18n("Not done: %1 (%2)", action.summary, reasons[action.outcome] || action.outcome)));
            const tokens = event.usage ? event.usage.input_tokens + event.usage.output_tokens : 0;
            if (event.model && tokens > 0) {
                appendEntry("notice", event.cost > 0
                    ? i18n("%1 · %2 tokens · %3", event.model, Number(tokens).toLocaleString(Qt.locale(), "f", 0), event.cost.toFixed(4))
                    : i18n("%1 · %2 tokens", event.model, Number(tokens).toLocaleString(Qt.locale(), "f", 0)));
            }
            if (event.stop === "cancelled") {
                appendEntry("notice", i18n("Stopped"));
            } else if (event.stop === "step_limit") {
                appendEntry("notice", i18n("Stopped after too many steps. Ask again to continue."));
            }
            break;
        }
        case "notice":
            appendEntry("notice", event.message || "");
            break;
        case "error":
            // An error the user fixes in settings gets a button that opens them.
            appendEntry(event.code === "not_configured" ? "setup" : "error", event.message || i18n("Request failed"));
            break;
        }
    }

    function cancel() {
        const xhr = session.activeStream;
        if (!xhr) {
            return;
        }
        session.activeStream = null;
        xhr.abort();
        if (session.conversationId) {
            request("POST", "/cancel", { conversation_id: session.conversationId }, function(data) {}, function(data) {});
        }
        appendEntry("notice", i18n("Stopped"));
        finishStream();
    }
}
