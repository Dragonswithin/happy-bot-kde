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
 * daemon status and the current instant file-search hits. It talks to the
 * daemon (`/health`, `/search`, `/open`, `/ask`, `/cancel`, `/approve`)
 * through its own DaemonClient.qml, which owns the address and the bearer
 * token. main.qml creates exactly one instance and supplies `configuredUrl`.
 * `needsSetup` is true while the daemon reports that no AI model is chosen.
 *
 * Conversation: `ask` posts to `/ask`, which answers with a server-sent
 * event stream. XMLHttpRequest reports the growing response at readyState
 * LOADING; `consumeStream` parses the new part into events and `applyEvent`
 * turns them into `entries`. Each entry is `{kind, text, stage, callId,
 * approvalId, detail, canRemember, started, progress}` (`stage`, not `state`, because every QML
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
 *   display) and `progress` the latest status line it reported.
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
 * `deleteConversation` removes one; deleting the open one starts a new one. `cancel` aborts
 * the request, which makes the daemon stop the turn.
 *
 * Instant search: `searchFiles` may be called on every keystroke. It asks the
 * daemon for quick results (`/quick`: answers, windows, applications,
 * settings pages, conversations; `quickHits`) and for at most `searchLimit`
 * file matches (`/search`; `fileHits`) at once; `hits` is both, quick first.
 * A quick hit has `kind` "quick" and an `action`; `activateQuick` carries it
 * out. Replies
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

    readonly property ListModel entries: ListModel {}
    property var history: []
    readonly property bool hasTranscript: entries.count > 0
    property int pendingApprovals: 0

    property int searchLimit: 8
    property var quickHits: []
    property var fileHits: []
    readonly property var hits: quickHits.concat(fileHits)
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
            started: Date.now(), progress: ""
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
    function setEntryStage(callId, stage) {
        const index = findEntry("callId", callId);
        if (index >= 0 && session.entries.get(index).kind === "tool") {
            session.entries.setProperty(index, "stage", stage);
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
            session.setStatus("idle", i18n("Ready"));
        }, function(data) {
            session.setStatus("offline", data.error || i18n("The assistant is not running"));
        });
    }

    function clearSearch() {
        session.searchSequence += 1;
        session.quickHits = [];
        session.fileHits = [];
        session.searchError = "";
        session.searchErrorCode = "";
    }

    /** `mode` "files" asks only for file matches, "answer" only for quick results; anything else both. */
    function searchFiles(text, mode) {
        const query = (text || "").trim();
        if (query.length === 0) {
            clearSearch();
            return;
        }
        session.searchSequence += 1;
        const sequence = session.searchSequence;
        if (mode === "files") {
            session.quickHits = [];
        } else {
            request("GET", "/quick?q=" + encodeURIComponent(query), null, function(data) {
                if (sequence === session.searchSequence) {
                    session.quickHits = data.results || [];
                }
            }, function(data) {
                if (sequence === session.searchSequence) {
                    session.quickHits = [];
                }
            });
        }
        if (mode === "answer") {
            session.fileHits = [];
            session.searchError = "";
            return;
        }
        request("GET", "/search?limit=" + session.searchLimit + "&q=" + encodeURIComponent(query), null, function(data) {
            if (sequence !== session.searchSequence) {
                return;
            }
            session.searchError = "";
            session.searchErrorCode = "";
            session.fileHits = data.hits || [];
        }, function(data) {
            if (sequence !== session.searchSequence) {
                return;
            }
            session.fileHits = [];
            session.searchError = data.error || i18n("Search failed");
            session.searchErrorCode = data.code || "tool_failed";
        });
    }

    /** Carries out a quick result: a conversation is opened here, anything else by the daemon. */
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

    function newChat() {
        if (session.busy) {
            cancel();
        }
        session.conversationId = "";
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
        xhr.send(JSON.stringify({ message: text, conversation_id: session.conversationId }));
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
            setEntryStage(event.id, event.ok ? "ok" : "failed");
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
