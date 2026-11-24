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
 * when the popup was opened from the floating button or the hotkey
 * (`captureApplication`), or null. While set, it is sent with every request
 * as `about_window`, so the user never has to say which application they
 * mean; the welcome screen's help shortcut names it (AssistantWelcome.qml),
 * and it does not limit what they can ask about. `helpChat` is set when the
 * chat was started from that shortcut: its requests also carry
 * `full_context`, so the daemon adds the selected text, the window's controls
 * and its open file (src/happy_bot/app_context.py, which also decides which
 * AI may see any of it). A new or reopened chat clears `helpChat`; opening
 * from the panel clears `helpWith` (`forgetApplication`).
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
 * The file finder: nothing is searched while the user types a request or a
 * reply. Only after they choose "Find a file" (`startFindingFiles`, which
 * sets `findingFiles` until `stopFindingFiles`) does typing call
 * `searchFiles`, which asks the daemon for at most `searchLimit` file
 * matches (`/search`; `hits`). `activateQuick` carries out a file match's
 * actions (show in the file manager, copy the path) through the daemon. Replies
 * can arrive out of order, so each request carries a sequence number and a
 * reply is applied only if it is the newest one sent. `hits` is a list of
 * `{title, location, snippet, kind}`; `searchError`/`searchErrorCode` carry
 * the daemon's message and code ("not_configured", "tool_failed") when the
 * last search failed.
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
    property var models: []
    property string chatModel: ""
    property var helpWith: null
    property string helpWithIcon: ""  // the application's icon name, for the welcome screen only
    property bool helpChat: false  // this chat began with "Help with …": requests carry the full context
    property var ui: ({
        robot_mascot: false, popup_width: 30, popup_height: 26, floating_opacity: 40, floating_x: -1, floating_y: -1,
        imported: []
    })
    property bool uiLoaded: false

    readonly property ListModel entries: ListModel {}
    property var history: []
    readonly property bool hasTranscript: entries.count > 0
    property int pendingApprovals: 0

    property int searchLimit: 8
    property bool findingFiles: false
    property var hits: []
    property string searchError: ""
    property string searchErrorCode: ""
    property int searchSequence: 0

    // The in-flight /ask request and how much of its response was parsed.
    property var activeStream: null
    property int streamOffset: 0
    property string streamBuffer: ""

    visible: false

    Component.onCompleted: {
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
            if (session.chatModel && !session.models.some(item => item.name === session.chatModel)) {
                session.chatModel = "";
            }
            session.setStatus("idle", i18n("Ready"));
        }, function(data) {
            session.setStatus("offline", data.error || i18n("The assistant is not running"));
        });
    }

    function clearSearch() {
        session.searchSequence += 1;
        session.hits = [];
        session.searchError = "";
        session.searchErrorCode = "";
    }

    /** "Find a file": typing now shows matching files, until `stopFindingFiles`. */
    function startFindingFiles() {
        clearSearch();
        session.findingFiles = true;
    }

    function stopFindingFiles() {
        session.findingFiles = false;
        clearSearch();
    }

    function searchFiles(text) {
        const query = (text || "").trim();
        if (query.length === 0) {
            clearSearch();
            return;
        }
        session.searchSequence += 1;
        const sequence = session.searchSequence;
        request("GET", "/search?limit=" + session.searchLimit + "&q=" + encodeURIComponent(query), null, function(data) {
            if (sequence !== session.searchSequence) {
                return;
            }
            session.searchError = "";
            session.searchErrorCode = "";
            session.hits = data.hits || [];
        }, function(data) {
            if (sequence !== session.searchSequence) {
                return;
            }
            session.hits = [];
            session.searchError = data.error || i18n("Search failed");
            session.searchErrorCode = data.code || "tool_failed";
        });
    }

    /** Carries out an action (`{type, target}`) through the daemon's `/quick/activate`, such as a file match's
     *  "show in the file manager" or "copy path"; a conversation is opened here instead. */
    function activateQuick(hit) {
        if (hit.action.type === "conversation") {
            openConversation(hit.action.target);
            return;
        }
        request("POST", "/quick/activate", { action: hit.action }, function(data) {}, function(data) {
            session.appendEntry("error", data.error || i18n("Could not open %1", hit.title));
        });
    }

    function openLocation(location) {
        request("POST", "/open", { location: location }, function(data) {}, function(data) {
            session.appendEntry("error", data.error || i18n("Could not open %1", location));
        });
    }

    function refreshHistory() {
        request("GET", "/conversations", null, function(data) {
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

    function openConversation(conversationId) {
        if (session.busy || conversationId === session.conversationId) {
            return;
        }
        request("GET", "/conversation?id=" + encodeURIComponent(conversationId), null, function(data) {
            session.conversationId = data.id;
            session.helpChat = false;
            session.chatModel = session.models.some(item => item.name === data.model) ? data.model : "";
            session.replay(data.events || []);
        }, function(data) {
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
        request("GET", "/context/app", null, function(data) {
            session.helpWith = data.app || data.title
                ? { app: data.app, "class": data["class"], title: data.title, window: data.window || "" } : null;
            session.helpWithIcon = session.helpWith ? data.icon || "" : "";
        }, function(data) {
            session.helpWith = null;
            session.helpWithIcon = "";
        });
    }

    function forgetApplication() {
        session.helpWith = null;
        session.helpWithIcon = "";
    }

    function newChat() {
        if (session.busy) {
            cancel();
        }
        session.conversationId = "";
        session.chatModel = "";
        session.helpChat = false;
        session.entries.clear();
        refreshStatus();
    }

    /** Sends one request to the assistant. Returns false if it was not sent. */
    function ask(message) {
        const text = (message || "").trim();
        if (!text || session.busy) {
            return false;
        }
        session.busy = true;
        setStatus("thinking", i18n("Thinking"));
        appendEntry("user", text);
        client.withToken(() => startStream(text, true));
        return true;
    }

    function startStream(text, mayReload) {
        const xhr = new XMLHttpRequest();
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
                    client.loadToken(() => session.startStream(text, false));
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
        const body = { message: text, conversation_id: session.conversationId, model: session.chatModel };
        if (session.helpWith) {
            body.about_window = session.helpWith;
            body.full_context = session.helpChat;
        }
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
