// SPDX-License-Identifier: MIT
import QtQuick
import QtTest
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui" as HappyBot

Item {
    function i18n(message) { return message; }

    HappyBot.AssistantSession {
        id: session
        configuredUrl: "http://127.0.0.1:1"
        property var requests: []
        function request(method, path, payload, onSuccess, onFailure) {
            requests.push({ path: path, success: onSuccess, failure: onFailure });
        }
    }

    TestCase {
        name: "ClearHistory"
        when: windowShown

        function init() {
            session.clearSearch();
            session.resetTranscript();
            session.history = [];
            session.requests = [];
        }

        function test_searchClearDiscardsLateSuggestionsAndMatches() {
            session.conversationId = "keep";
            session.appendEntry("user", "A saved chat");
            session.showRecent();
            session.search("old query");
            const pending = session.requests.slice();
            compare(pending.length, 3);
            session.quickHits = [{ title: "Old result" }];
            const cleared = String(session.searchClearRevision + 1);
            verify(session.applyHistoryClears({ search_clear_revision: cleared }));
            pending[0].success({ results: [{ title: "Old suggestion" }] });
            pending[1].success({ results: [{ title: "Old quick match" }] });
            pending[2].success({ hits: [{ title: "Old file" }] });
            compare(session.hits.length, 0);
            compare(session.recentHits.length, 0);
            compare(session.searchedText, "");
            compare(session.searching, false);
            compare(session.conversationId, "keep");
            compare(session.entries.count, 1);

            session.search("new query");
            verify(!session.applyHistoryClears({ search_clear_revision: cleared }));
            compare(session.searchedText, "new query");
        }

        function test_conversationClearDiscardsLateTranscriptAndSidebar() {
            session.refreshHistory();
            session.openConversation("forgotten");
            const pending = session.requests.slice();
            compare(pending.length, 2);
            session.conversationId = "forgotten";
            session.appendEntry("user", "Old message");
            session.history = [{ id: "forgotten" }];
            session.busy = true;
            let aborted = false;
            session.activeStream = { abort: () => { aborted = session.activeStream === null; } };
            const cleared = String(session.conversationClearRevision + 1);
            verify(session.applyHistoryClears({ conversation_clear_revision: cleared }));
            verify(aborted);
            pending[0].success({ conversations: [{ id: "forgotten" }] });
            pending[1].success({ id: "forgotten", events: [{ type: "user", text: "Old message" }] });
            compare(session.entries.count, 0);
            compare(session.history.length, 0);
            compare(session.conversationId, "");
            compare(session.busy, false);

            // A fresh sidebar reply and chat started after deletion still belong here.
            const sidebar = session.requests.slice(pending.length).find(request => request.path === "/conversations");
            sidebar.success({ conversations: [{ id: "fresh" }] });
            compare(session.history[0].id, "fresh");
            session.appendEntry("user", "New message");
            verify(!session.applyHistoryClears({ conversation_clear_revision: cleared }));
            compare(session.entries.count, 1);
        }

        function test_earlierClearKeepsNewerChatOnConnection() {
            const beforeLaunch = session.conversationClearRevision - 60;
            const whileDisconnected = session.conversationClearRevision + 10;
            session.conversationId = "new";
            session.conversationCreatedAt = whileDisconnected + 10;
            session.appendEntry("user", "New message");
            verify(!session.applyHistoryClears({ conversation_clear_revision: String(beforeLaunch) }));
            verify(session.applyHistoryClears({ conversation_clear_revision: String(whileDisconnected) }));
            compare(session.conversationId, "new");
            compare(session.entries.count, 1);
        }
    }
}
