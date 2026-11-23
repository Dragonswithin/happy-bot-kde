/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick

import org.kde.plasma.plasma5support as P5Support

/**
 * Non-visual owner of one conversation with the per-user daemon.
 *
 * Holds the transcript, busy flag, daemon status and the current instant
 * file-search hits that PanelBar.qml, CompactRepresentation.qml and
 * ResultsPopup.qml display, and is the only place in the applet that talks
 * HTTP to the daemon (`/health`, `/search`, `/open`, `/ask`, `/screenshot`).
 * main.qml creates exactly one instance and supplies `daemonUrl`.
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
 * Requests are asynchronous XMLHttpRequest calls on the GUI thread; nothing
 * here blocks. A failed or unreachable daemon sets `status` to "offline" and
 * appends the error to the transcript instead of throwing. `status` is one of
 * "starting", "idle", "thinking" or "offline".
 */
Item {
    id: session

    property string daemonUrl: ""
    property string tokenFile: ""
    property string transcript: ""
    property string status: "starting"
    property string statusText: i18n("Starting")
    property bool busy: false

    readonly property bool hasTranscript: transcript.length > 0

    property var hits: []
    property string searchError: ""
    property string searchErrorCode: ""
    property int searchSequence: 0

    // Bearer token state. `tokenWaiters` are callbacks queued while one
    // `cat` is in flight, so concurrent requests share a single read.
    property string token: ""
    property var tokenWaiters: []

    visible: false

    Component.onCompleted: refreshStatus()

    Timer {
        interval: 12000
        repeat: true
        running: true
        onTriggered: session.refreshStatus()
    }

    function appendLine(prefix, text) {
        session.transcript += (session.transcript ? "\n\n" : "") + prefix + "\n" + text;
    }

    function setStatus(status, summary) {
        session.status = status;
        session.statusText = summary;
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

    function request(method, path, payload, onSuccess, onFailure) {
        if (session.token) {
            send(method, path, payload, onSuccess, onFailure, true);
        } else {
            loadToken(() => send(method, path, payload, onSuccess, onFailure, false));
        }
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
            session.appendLine(i18n("Error"), data.error || i18n("Could not open %1", location));
        });
    }

    function newChat() {
        session.transcript = "";
        refreshStatus();
    }

    /** Sends one request. `contextKind` is "combined", "clipboard" or "window". */
    function ask(message, contextKind) {
        const text = (message || "").trim();
        if (!text || session.busy) {
            return false;
        }
        session.busy = true;
        setStatus("thinking", i18n("Thinking"));
        appendLine(i18n("You"), text);
        request("POST", "/ask", { message: text, contextKind: contextKind || "combined" }, function(data) {
            session.busy = false;
            session.setStatus("idle", i18n("Ready"));
            session.appendLine(i18n("Assistant"), data.answer || i18n("No answer returned."));
        }, function(data) {
            session.busy = false;
            session.appendLine(i18n("Error"), data.error || i18n("Request failed"));
            session.refreshStatus();
        });
        return true;
    }

    function screenshotContext() {
        request("POST", "/screenshot", {}, function(data) {
            session.appendLine(i18n("Screenshot"), data.path
                ? i18n("Saved transient context screenshot: %1", data.path)
                : i18n("Screenshot captured."));
        }, function(data) {
            session.appendLine(i18n("Error"), data.error || i18n("Screenshot failed."));
        });
    }
}
