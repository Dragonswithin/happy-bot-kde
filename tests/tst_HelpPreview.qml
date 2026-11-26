// SPDX-License-Identifier: MIT
import QtQuick
import QtTest
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui" as HappyBot

Item {
    width: 800
    height: 700
    function i18n(message, arg) { return arg === undefined ? message : message.replace("%1", arg); }
    function i18np(single, plural, count) { return count === 1 ? single : plural; }
    function i18nc(context, message) { return message; }

    HappyBot.ResultsView {
        id: view
        session: HappyBot.AssistantSession {
            id: session
            property var capture
            property var sent
            function request(method, path, body, success, failure) {
                if (path === "/context/screenshot") capture = { body, success, failure };
            }
            function startStream(body, mayReload, xhr) { sent = body; }
        }
        onAccepted: text => session.ask(text)
    }

    TestCase {
        name: "HelpPreview"
        when: windowShown

        function findVisible(item, predicate) {
            if (!item.visible) return null;
            if (predicate(item)) return item;
            for (const child of item.children) {
                const match = findVisible(child, predicate);
                if (match) return match;
            }
            return null;
        }

        function init() {
            session.busy = false;
            session.resetTranscript();
            session.helpWith = { app: "Kate", window: "{kate}" };
            session.capture = null;
            session.sent = null;
            view.clearInput();
        }

        function clickTile(label) {
            const button = findVisible(view, item => item.text === label && typeof item.clicked === "function");
            verify(!!button);
            mouseClick(button);
        }

        function test_clickPreviewThenAsk() {
            verify(!session.capture);
            clickTile("Help with Kate");
            compare(session.capture.body.window, "{kate}");
            compare(session.capture.body.desktop, false);
            verify(view.helpVisible);
            compare(view.inputText, "");
            verify(!findVisible(view, item => item.text === "How can I help?"));
            view.setInput("How do I split the view?");
            keyClick(Qt.Key_Return);
            compare(session.entries.count, 0);
            session.capture.success({ id: "sample", url: Qt.resolvedUrl(
                "../plasmoid/io.github.dragonswithin.happybot/contents/images/happy-bot.svg").toString(), models: [] });
            tryVerify(() => !!findVisible(view, item => item.fillMode === Image.PreserveAspectFit && item.status === Image.Ready));
            verify(findVisible(view, item => String(item.text).includes("just for your reference")));
            compare(session.entries.count, 0);
            session.helpWith = { app: "Another window", window: "{other}" };
            keyClick(Qt.Key_Return);
            tryVerify(() => !!session.sent);
            compare(session.sent.message, "How do I split the view?");
            compare(session.sent.about_window.window, "{kate}");
            compare(session.sent.screenshot_id, "sample");
            verify(!view.helpVisible);
        }

        function test_backDiscardsLateCapture() {
            clickTile("Help with Kate");
            const previous = session.capture;
            clickTile("Back");
            verify(!view.helpVisible);
            session.helpWith = null;
            clickTile("Desktop help");
            compare(session.capture.body.desktop, true);
            previous.success({ id: "old", url: "file:///old.png" });
            verify(session.capturing);
            session.capture.success({ taken: false, reason: "disabled" });
            verify(!session.capturing);
            verify(findVisible(view, item => String(item.text).includes("turned off")));
            keyClick(Qt.Key_Escape);
            verify(!view.helpVisible);
            verify(!session.helpChat);
        }
    }
}
