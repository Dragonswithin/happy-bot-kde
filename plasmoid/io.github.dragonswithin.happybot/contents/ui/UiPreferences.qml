// SPDX-License-Identifier: MIT
pragma ComponentBehavior: Bound
import QtQuick

// Appearance and Sounds share the daemon's /ui settings. Apply edits in the order the user
// made them, since a mascot change can change the theme of all ten event sounds at once.
QtObject {
    id: store
    required property var client
    property var saved: null
    property var pending: []
    property int readSequence: 0
    signal problem(string message)

    readonly property var ui: {
        if (!saved) return null;
        const value = Object.assign({}, saved);
        for (const change of pending) {
            const previousRobot = value.robot_style;
            const sounds = Object.assign({}, value.event_sounds);
            Object.assign(value, change);
            if (value.sounds_follow_mascot && value.robot_style !== previousRobot) {
                for (const event of Object.keys(sounds))
                    sounds[event] = Object.assign({}, sounds[event], {theme: value.robot_style});
            }
            if (change.event_sounds) {
                for (const [event, fields] of Object.entries(change.event_sounds))
                    sounds[event] = Object.assign({}, sounds[event], fields);
            }
            value.event_sounds = sounds;
        }
        return value;
    }

    function read() {
        if (pending.length) return;
        const sequence = ++readSequence;
        client.request("GET", "/health", null, data => {
            if (readSequence === sequence) saved = data.ui || null;
        }, data => {
            if (readSequence === sequence) problem(data.error || i18n("The assistant is not running"));
        });
    }

    function save(change) {
        readSequence++;
        pending = pending.concat([change]);
        if (pending.length === 1) sendNext();
    }

    function sendNext() {
        function finish() {
            store.pending = store.pending.slice(1);
            if (store.pending.length) store.sendNext();
        }
        client.request("POST", "/ui", {changes: pending[0]}, data => {
            store.saved = data.ui;
            store.problem("");
            finish();
        }, data => {
            store.problem(data.error || i18n("That could not be saved"));
            finish();
            store.read();
        });
    }
}
