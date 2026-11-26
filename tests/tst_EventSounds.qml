// SPDX-License-Identifier: MIT
import QtQuick
import QtTest
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui" as HappyBot

Item {
    width: 500
    height: 740
    function i18n(text, first, second) {
        return text.replace("%1", first ?? "").replace("%2", second ?? "");
    }

    QtObject {
        id: api
        property var requests: []
        function request(method, path, body, success, failure) {
            requests.push({method, path, body, success, failure});
        }
    }
    HappyBot.UiPreferences { id: store; client: api }
    HappyBot.EventSounds {
        id: editor
        width: parent.width
        choices: store.ui?.event_sounds ?? ({})
        onEdited: (event, fields) => store.save({event_sounds: {[event]: fields}})
    }
    SignalSpy { id: sounds; target: editor; signalName: "previewRequested" }

    TestCase {
        name: "EventSounds"
        when: windowShown
        function init() {
            api.requests = [];
            store.pending = [];
            store.saved = {event_sounds: {alarm: {enabled: false, theme: "watt"}}};
            sounds.clear();
            waitForPolish(editor);
        }

        function test_quietEventsHaveAllSoundThemesAndAPreview() {
            const ids = ["open", "error", "complete", "alarm", "reminder", "attention",
                         "mic_ready", "mic_done", "background", "nudge"];
            for (const id of ids) {
                const themes = findChild(editor, "theme-" + id);
                compare(themes.count, 11);
                compare(themes.valueAt(10), "wand");
                verify(!findChild(editor, "enable-" + id).checked);
                findChild(editor, "preview-" + id).clicked();
                compare(sounds.signalArguments[sounds.count - 1][0], id);
                compare(sounds.signalArguments[sounds.count - 1][1], id === "alarm" ? "watt" : "pip");
            }
            compare(api.requests.length, 0);
        }

        function test_wandFollowsAppearanceInQueuedEdits() {
            store.saved = {robot_mascot: true, robot_style: "watt", sounds_follow_mascot: true,
                           event_sounds: {alarm: {enabled: true, theme: "watt"}}};
            store.save({robot_mascot: false});
            compare(findChild(editor, "theme-alarm").currentText, "Wand");
            verify(findChild(editor, "enable-alarm").checked);
            findChild(editor, "preview-alarm").clicked();
            compare(sounds.signalArguments[0][0], "alarm");
            compare(sounds.signalArguments[0][1], "wand");
        }

        function test_quickEditsKeepTheirOrder() {
            const alarm = findChild(editor, "enable-alarm");
            alarm.click();
            const themes = findChild(editor, "theme-alarm");
            themes.activated(7); // Sprocket
            verify(alarm.checked);
            compare(themes.currentText, "Sprocket");
            compare(api.requests.length, 1);
            compare(api.requests[0].body.changes.event_sounds.alarm, {enabled: true});
            api.requests[0].success({ui: {event_sounds: {alarm: {enabled: true, theme: "watt"}}}});
            compare(api.requests.length, 2);
            compare(api.requests[1].body.changes.event_sounds.alarm, {theme: "sprocket"});
            api.requests[1].success({ui: {event_sounds: {alarm: {enabled: true, theme: "sprocket"}}}});
            verify(alarm.checked);
            compare(themes.currentText, "Sprocket");
        }
    }
}
