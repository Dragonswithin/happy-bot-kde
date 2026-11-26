// SPDX-License-Identifier: MIT
import QtQuick
import QtTest
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui" as HappyBot

Item {
    id: view
    width: 850
    height: 1800

    function i18n(message, arg) { return arg === undefined ? message : message.replace("%1", arg); }
    function i18np(single, plural, count) { return i18n(count === 1 ? single : plural, count); }

    Component {
        id: historyPage
        HappyBot.SetupHistory {
            width: view.width
            page: QtObject {
                id: dialog
                readonly property var settings: ({folders: {}, personal: {}, history_days: 30})
                readonly property var effectiveFolders: ({})
                property var requests: []
                property string reportText: ""
                property bool reportError: false
                function report(text, error) {
                    reportText = text;
                    reportError = error;
                }
                readonly property QtObject client: QtObject {
                    function request(method, path, body, success, failure) {
                        dialog.requests.push({method, path, body, success, failure});
                    }
                }
            }
        }
    }

    TestCase {
        name: "HistoryPage"
        when: windowShown
        readonly property var kinds: ["search", "conversations", "activity", "undo", "usage", "cache"]
        property var section

        function init() {
            section = createTemporaryObject(historyPage, view);
            verify(section !== null);
            waitForPolish(section);
        }

        function button(prefix, kind) {
            const item = findChild(section, prefix + "-" + kind);
            verify(item !== null, "Missing " + prefix + " button for " + kind);
            return item;
        }

        function test_confirmAndCancel_data() {
            return kinds.map(kind => ({tag: kind, kind: kind}));
        }

        function test_confirmAndCancel(data) {
            const clear = button("clear", data.kind);
            const cancel = button("cancel", data.kind);
            const requests = section.page.requests;
            mouseClick(clear);
            tryCompare(cancel, "visible", true);
            compare(requests.length, 0);
            mouseClick(cancel);
            tryCompare(cancel, "visible", false);
            compare(requests.length, 0);
            mouseClick(clear);
            tryCompare(cancel, "visible", true);
            mouseClick(clear);
            compare(requests.length, 1);
            compare(requests[0].method, "POST");
            compare(requests[0].path, "/history/clear");
            compare(requests[0].body, {kind: data.kind});
            verify(!cancel.enabled);
            for (const kind of kinds)
                verify(!button("clear", kind).enabled, "Pending request must disable " + kind);
            mouseClick(clear);
            compare(requests.length, 1);
            requests[0].success({ok: true, kind: data.kind});
            tryCompare(clear, "enabled", true);
            verify(!cancel.visible);
            verify(!section.page.reportError && section.page.reportText.length > 0);
        }

        function test_retryAfterFailure() {
            const clear = button("clear", "search");
            const cancel = button("cancel", "search");
            const requests = section.page.requests;
            mouseClick(clear);
            mouseClick(clear);
            compare(requests.length, 1);
            requests[0].failure({error: "Storage busy"});
            verify(section.page.reportError);
            compare(section.page.reportText, "Storage busy");
            tryCompare(clear, "enabled", true);
            verify(cancel.visible && cancel.enabled);
            mouseClick(clear);
            compare(requests.length, 2);
            requests[1].success({ok: true, kind: "search"});
            tryCompare(clear, "enabled", true);
            verify(!section.page.reportError);
        }
    }
}
