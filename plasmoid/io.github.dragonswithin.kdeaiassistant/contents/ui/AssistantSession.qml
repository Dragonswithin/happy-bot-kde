/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick

import org.kde.plasma.plasma5support as P5Support

/**
 * Non-visual owner of one conversation with the per-user daemon.
 *
 * Holds everything PanelBar.qml, CompactRepresentation.qml and
 * ResultsPopup.qml display: the conversation `entries`, the busy flag, the
 * daemon status and the current instant file-search hits. It is the only
 * place in the applet that talks HTTP to the daemon (`/health`, `/search`,
 * `/open`, `/ask`, `/cancel`). main.qml creates exactly one instance and
 * supplies `daemonUrl` and `tokenFile`.
 *
 * Conversation: `ask` posts to `/ask`, which answers with a server-sent
 * event stream. XMLHttpRequest reports the growing response at readyState
 * LOADING; `consumeStream` parses the new part into events and `applyEvent`
 * turns them into `entries`. Each entry is `{kind, text, state, callId}`:
 *
 * - kind "user", "assistant" (Markdown, grows as text streams in), "notice"
 *   and "error" use `text`.
 * - kind "tool" is one tool call: `text` is its display name, `state` is
 *   "running", "ok" or "failed", `callId` links the result to the call.
 *
 * The daemon keeps the history; `conversationId` (from the stream's first
 * event) is sent with follow-ups and cleared by `newChat`. `cancel` aborts
 * the request, which makes the daemon stop the turn.
 *
 * Instant search: `searchFiles` may be called on every keystroke. Replies
 * can arrive out of order, so each request carries a sequence number and a
 * reply is applied only if it is the newest one sent. `hits` is a list of
 * `{title, location, snippet, kind}`; `searchError`/`searchErrorCode` carry
 * the daemon's message and code ("not_configured", "tool_failed") when the
 * last search failed.
 *
 * Every request carries the daemon's bearer token. The daemon writes it to
 * `tokenFile` (0600, in the user's runtime directory) and regenerates it on
 * each start. QML's XMLHttpRequest refuses local files, so the token is read
 * by running `cat` through Plasma's "executable" data source. It is loaded
 * on first use and reloaded once when the daemon answers 401, which is what
 * a daemon restart looks like from here.
 *
 * Nothing here blocks: all requests are asynchronous on the GUI thread. A
 * failed or unreachable daemon sets `status` to "offline" and adds an error
 * entry instead of throwing. `status` is one of "starting", "idle",
 * "thinking" or "offline".
 */
Item {
    id: session

    property string daemonUrl: ""
    property string tokenFile: ""
    property string status: "starting"
    property string statusText: i18n("Starting")
    property bool busy: false
    property string conversationId: ""

    readonly property ListModel entries: ListModel {}
    readonly property bool hasTranscript: entries.count > 0

    property var hits: []
    property string searchError: ""
    property string searchErrorCode: ""
    property int searchSequence: 0

    // Bearer token state. `tokenWaiters` are callbacks queued while one
    // `cat` is in flight, so concurrent requests share a single read.
    property string token: ""
    property var tokenWaiters: []

    // The in-flight /ask request and how much of its response was parsed.
    property var activeStream: null
    property int streamOffset: 0
    property string streamBuffer: ""

    visible: false

    Component.onCompleted: refreshStatus()

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

    function appendEntry(kind, text, state, callId) {
        session.entries.append({ kind: kind, text: text || "", state: state || "", callId: callId || "" });
    }

    P5Support.DataSource {
        id: tokenReader
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            disconnectSource(source);
            session.token = String(data["stdout"] || "").trim();
            const waiters = session.tokenWaiters;
            session.tokenWaiters = [];
            waiters.forEach(waiter => waiter());
        }
    }

    function loadToken(then) {
        // The path is interpolated into a shell command; a quote in it would
        // break out of the quoting, so such a path is treated as unreadable.
        if (!session.tokenFile || session.tokenFile.indexOf("'") !== -1) {
            session.token = "";
            then();
            return;
        }
        session.tokenWaiters.push(then);
        if (session.tokenWaiters.length === 1) {
            tokenReader.connectSource("cat -- '" + session.tokenFile + "'");
        }
    }

    function withToken(then) {
        if (session.token) {
            then();
        } else {
            loadToken(then);
        }
    }

    function request(method, path, payload, onSuccess, onFailure) {
        withToken(() => send(method, path, payload, onSuccess, onFailure, true));
    }

    /** `mayReload`: retry once with a freshly read token if the daemon says 401. */
    function send(method, path, payload, onSuccess, onFailure, mayReload) {
        const xhr = new XMLHttpRequest();
        xhr.open(method, session.daemonUrl + path);
        xhr.setRequestHeader("Content-Type", "application/json");
        xhr.setRequestHeader("Authorization", "Bearer " + session.token);
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) {
                return;
            }
            if (xhr.status === 0) {
                onFailure({ ok: false, error: i18n("The assistant is not running") });
                return;
            }
            if (xhr.status === 401 && mayReload) {
                session.loadToken(() => session.send(method, path, payload, onSuccess, onFailure, false));
                return;
            }
            let data = {};
            try {
                data = JSON.parse(xhr.responseText || "{}");
            } catch (error) {
                data = { ok: false, error: i18n("Invalid response from the assistant") };
            }
            if (xhr.status >= 200 && xhr.status < 300 && data.ok !== false) {
                onSuccess(data);
            } else {
                onFailure(data);
            }
        };
        xhr.send(payload ? JSON.stringify(payload) : null);
    }

    function refreshStatus() {
        if (session.busy) {
            return;
        }
        request("GET", "/health", null, function(data) {
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

    function searchFiles(text) {
        const query = (text || "").trim();
        if (query.length === 0) {
            clearSearch();
            return;
        }
        session.searchSequence += 1;
        const sequence = session.searchSequence;
        request("GET", "/search?limit=8&q=" + encodeURIComponent(query), null, function(data) {
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

    function openLocation(location) {
        request("POST", "/open", { location: location }, function(data) {}, function(data) {
            session.appendEntry("error", data.error || i18n("Could not open %1", location));
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
        withToken(() => startStream(text, true));
        return true;
    }

    function startStream(text, mayReload) {
        const xhr = new XMLHttpRequest();
        session.activeStream = xhr;
        session.streamOffset = 0;
        session.streamBuffer = "";
        xhr.open("POST", session.daemonUrl + "/ask");
        xhr.setRequestHeader("Content-Type", "application/json");
        xhr.setRequestHeader("Authorization", "Bearer " + session.token);
        xhr.onreadystatechange = function() {
            if (session.activeStream !== xhr) {
                return;
            }
            if (xhr.readyState === XMLHttpRequest.LOADING && xhr.status === 200) {
                session.consumeStream(xhr);
            } else if (xhr.readyState === XMLHttpRequest.DONE) {
                if (xhr.status === 401 && mayReload) {
                    session.loadToken(() => session.startStream(text, false));
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
        for (let index = 0; index < session.entries.count; index++) {
            if (session.entries.get(index).state === "running") {
                session.entries.setProperty(index, "state", "failed");
            }
        }
        refreshStatus();
    }

    function toolLabel(name) {
        return name.replace("__", ": ").replace(/_/g, " ");
    }

    function applyEvent(event) {
        const last = session.entries.count - 1;
        switch (event.type) {
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
            appendEntry("tool", toolLabel(event.name), "running", event.id);
            break;
        case "tool_result":
            for (let index = last; index >= 0; index--) {
                if (session.entries.get(index).callId === event.id) {
                    session.entries.setProperty(index, "state", event.ok ? "ok" : "failed");
                    break;
                }
            }
            break;
        case "done":
            if (event.stop === "cancelled") {
                appendEntry("notice", i18n("Stopped."));
            } else if (event.stop === "step_limit") {
                appendEntry("notice", i18n("Stopped after too many steps. Ask again to continue."));
            }
            break;
        case "error":
            appendEntry("error", event.message || i18n("Request failed"));
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
        appendEntry("notice", i18n("Stopped."));
        finishStream();
    }
}
