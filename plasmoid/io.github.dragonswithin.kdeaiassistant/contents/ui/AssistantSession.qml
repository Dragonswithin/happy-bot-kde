/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick

/**
 * Non-visual owner of one conversation with the per-user daemon.
 *
 * Holds the transcript, busy flag and daemon status that PanelBar.qml,
 * CompactRepresentation.qml and ResultsPopup.qml display, and is the only
 * place in the applet that talks HTTP to the daemon (`/health`, `/ask`,
 * `/screenshot`). main.qml creates exactly one instance and supplies
 * `daemonUrl`.
 *
 * Requests are asynchronous XMLHttpRequest calls on the GUI thread; nothing
 * here blocks. A failed or unreachable daemon sets `status` to "offline" and
 * appends the error to the transcript instead of throwing. `status` is one of
 * "starting", "idle", "thinking" or "offline".
 */
Item {
    id: session

    property string daemonUrl: ""
    property string transcript: ""
    property string status: "starting"
    property string statusText: i18n("Starting")
    property bool busy: false

    readonly property bool hasTranscript: transcript.length > 0

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

    function request(method, path, payload, onSuccess, onFailure) {
        const xhr = new XMLHttpRequest();
        xhr.open(method, session.daemonUrl + path);
        xhr.setRequestHeader("Content-Type", "application/json");
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) {
                return;
            }
            if (xhr.status === 0) {
                onFailure({ ok: false, error: i18n("The assistant is not running") });
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
            session.setStatus(data.status || "idle", i18n("Ready"));
        }, function(data) {
            session.setStatus("offline", data.error || i18n("The assistant is not running"));
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
            session.setStatus("offline", data.error || i18n("Request failed"));
            session.appendLine(i18n("Error"), data.error || i18n("Request failed"));
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
