/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtCore as QtCore
import QtQuick

import org.kde.plasma.plasma5support as P5Support

/**
 * The applet's connection to the per-user daemon: where it is, the bearer
 * token, and authenticated JSON requests. AssistantSession.qml and the
 * settings pages each own one instance, so the address and token logic exist
 * in one place.
 *
 * Address: `configuredUrl` (the applet's `daemonUrl` setting) if set, else
 * the per-uid loopback port defined in src/kde_ai_assistant/runtime_paths.py.
 *
 * Token: the daemon writes it (0600) to `tokenFile` in the user's runtime
 * directory and regenerates it on each start. QML's XMLHttpRequest refuses
 * local files, so it is read by running `cat` through Plasma's "executable"
 * data source: on first use, and once more when the daemon answers 401,
 * which is what a daemon restart looks like from here. `tokenWaiters` are
 * callbacks queued while one read is in flight so concurrent requests share
 * it.
 *
 * `request` never throws. `onFailure` receives `{ok: false, error, code}`;
 * an unreachable daemon is reported with code "offline".
 */
Item {
    id: client

    property string configuredUrl: ""

    // StandardPaths returns a file:// URL in QML; the scheme is stripped so
    // the value is a plain directory path such as /run/user/1000.
    readonly property string runtimeLocation: String(QtCore.StandardPaths.writableLocation(QtCore.StandardPaths.RuntimeLocation)).replace(/^file:\/\//, "")
    readonly property int sessionUid: {
        const match = runtimeLocation.match(/\/run\/user\/([0-9]+)/);
        return match ? parseInt(match[1]) : 1000;
    }
    readonly property string daemonUrl: configuredUrl.length > 0
        ? configuredUrl
        : "http://127.0.0.1:" + (19000 + Math.max(0, sessionUid - 1000))
    readonly property string tokenFile: runtimeLocation + "/kde-ai-assistant/token"

    property string token: ""
    property var tokenWaiters: []

    visible: false

    P5Support.DataSource {
        id: tokenReader
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            disconnectSource(source);
            client.token = String(data["stdout"] || "").trim();
            const waiters = client.tokenWaiters;
            client.tokenWaiters = [];
            waiters.forEach(waiter => waiter());
        }
    }

    function loadToken(then) {
        // The path is interpolated into a shell command; a quote in it would
        // break out of the quoting, so such a path is treated as unreadable.
        if (client.tokenFile.indexOf("'") !== -1) {
            client.token = "";
            then();
            return;
        }
        client.tokenWaiters.push(then);
        if (client.tokenWaiters.length === 1) {
            tokenReader.connectSource("cat -- '" + client.tokenFile + "'");
        }
    }

    function withToken(then) {
        if (client.token) {
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
        xhr.open(method, client.daemonUrl + path);
        xhr.setRequestHeader("Content-Type", "application/json");
        xhr.setRequestHeader("Authorization", "Bearer " + client.token);
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) {
                return;
            }
            if (xhr.status === 0) {
                onFailure({ ok: false, error: i18n("The assistant is not running"), code: "offline" });
                return;
            }
            if (xhr.status === 401 && mayReload) {
                client.loadToken(() => client.send(method, path, payload, onSuccess, onFailure, false));
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
}
