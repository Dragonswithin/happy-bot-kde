// SPDX-License-Identifier: MIT
import QtQuick
import QtTest
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui" as HappyBot

Item {
    width: 900
    height: 700

    function i18n(text, arg) { return arg === undefined ? text : text.replace("%1", arg); }
    function i18np(one, many, count) { return count === 1 ? one : many; }
    function i18nc(context, text) { return text; }

    HappyBot.ResultsView {
        id: view
        session: HappyBot.AssistantSession {
            id: session
            function request(method, path, body, success, failure) {}
        }
    }

    TestCase {
        name: "ViewHeading"
        when: windowShown
        property var heading

        function initTestCase() {
            heading = findChild(view, "viewHeading");
            verify(heading);
            session.ui = Object.assign({}, session.ui, { start_screen: ["files", "web", "help", "system"] });
        }

        function init() {
            session.stopFinding();
            session.stopFixing();
            session.resetTranscript();
            session.history = [];
        }

        function button(item, text) {
            if (!item.visible) return null;
            if (item.text === text && typeof item.clicked === "function") return item;
            for (const child of item.children) {
                const found = button(child, text);
                if (found) return found;
            }
            return null;
        }

        function test_startScreenTiles_data() {
            return ["Find a file", "Search the web", "System info", "Desktop help"].map(text => ({ tag: text, text }));
        }

        function test_startScreenTiles(data) {
            compare(heading.text, "Start screen");
            tryVerify(() => !!button(view, data.text));
            waitForRendering(view);
            mouseClick(button(view, data.text));
            tryCompare(heading, "text", data.text);
            waitForRendering(view);
            mouseClick(button(view, "Back"));
            tryCompare(heading, "text", "Start screen");
        }

        function test_articleAndSelection() {
            session.startFinding("web");
            session.openArticle("Robots", "Robots");
            compare(heading.text, "Wikipedia");
            session.closeArticle();
            compare(heading.text, "Search the web");
            session.stopFinding();
            session.fixing = { text: "hello", app: "Kate" };
            compare(heading.text, "Fix selected text");
        }

        function test_chatTitles() {
            session.appendEntry("user", "How do I tile windows?");
            compare(heading.text, "Chat with Happy Bot");
            session.conversationId = "a";
            session.history = [{ id: "a", title: "Tiling windows", updated: 0 }];
            compare(heading.text, "Tiling windows");
            session.helpWindow = { app: "Kate" };
            session.helpChat = true;
            compare(heading.text, "Help with Kate");
        }
    }
}
