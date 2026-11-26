// SPDX-License-Identifier: MIT
import QtQuick
import QtTest
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui" as HappyBot

Item {
    width: 800
    height: 700
    function i18n(text, value) { return value === undefined ? text : text.replace("%1", value); }
    function i18np(one, many, count) { return count === 1 ? one : many; }
    function i18nc(context, text) { return text; }

    HappyBot.ResultsView {
        id: view
        session: HappyBot.AssistantSession {
            id: session
            property var requests: []
            function request(method, path, body, success, failure) {
                requests.push({ method, path, body, success, failure });
            }
        }
        onHitActivated: location => session.openLocation(location)
    }
    SignalSpy { id: edits; target: view; signalName: "queryEdited" }

    TestCase {
        name: "WebStartIntegration"
        when: windowShown
        readonly property var site: ({ host: "example.org", location: "https://example.org/", title: "Example", pinned: false })
        readonly property string query: "keyboard shortcuts"

        function requestsAt(path) { return session.requests.filter(req => req.path === path); }
        function latest(path) {
            const found = requestsAt(path);
            verify(found.length > 0, "Expected a request for " + path);
            return found[found.length - 1];
        }
        function data(sites, searches) {
            return { sites, searches, history_enabled: session.ui.search_history, search_clear_revision: 0 };
        }

        function init() {
            session.stopFinding();
            view.clearInput();
            session.webStartData = {};
            session.ui = Object.assign({}, session.ui, { search_history: true });
            session.requests = [];
            edits.clear();
            session.startFinding("web");
            view.focusInput();
            verify(view.webStartVisible);
            compare(session.webStartLoading, true);
        }

        function test_openAndRepeatFromKeyboard() {
            latest("/web/start").success(data([site], [query]));
            tryVerify(() => !!findChild(view, "webSite-" + site.host));
            compare(view.webStartIndex, -1);
            keyClick(Qt.Key_Return);
            compare(requestsAt("/open").length, 0);
            keyClick(Qt.Key_Down);
            compare(view.webStartIndex, 0);
            keyClick(Qt.Key_Return);
            compare(latest("/open").body.location, site.location);
            compare(requestsAt("/web/search/remember").length, 0);
            keyClick(Qt.Key_Down);
            compare(view.webStartIndex, 1);
            keyClick(Qt.Key_Return);
            compare(view.inputText, query);
            compare(edits.signalArguments[edits.count - 1][0], query);
            compare(latest("/web/search/remember").body.query, query);
            compare(view.webStartVisible, false);
            compare(requestsAt("/open").length, 1);
        }

        function test_menuFromFieldSavesAndRejectsOlderRead() {
            latest("/web/start").success(data([site], []));
            keyClick(Qt.Key_Down);
            keyClick(Qt.Key_F10, Qt.ShiftModifier);
            const menu = findChild(view, "webSiteMenu");
            tryCompare(menu, "opened", true);
            mouseClick(menu.itemAt(0));
            const pin = latest("/web/site");
            compare(pin.body.action, "pin");
            compare(pin.body.url, site.location);
            compare(requestsAt("/open").length, 0);
            session.loadWebStart();
            const earlier = latest("/web/start");
            pin.success(data([Object.assign({}, site, { pinned: true })], []));
            earlier.success(data([site], []));
            compare(session.webStartData.sites[0].pinned, true);
        }

        function test_clearDropsOutstandingReadAndWriteResponses() {
            latest("/web/start").success(data([site], [query]));
            session.loadWebStart();
            const staleRead = latest("/web/start");
            session.changeWebSite(site.location, "pin");
            const staleWrite = latest("/web/site");
            verify(session.applyHistoryClears({ search_clear_revision: session.searchClearRevision + 1 }));
            staleRead.success(data([site], [query]));
            staleWrite.success(data([site], [query]));
            compare((session.webStartData.searches || []).length, 0);
            const refresh = latest("/web/start");
            verify(refresh !== staleRead);
            refresh.success(data([Object.assign({}, site, { pinned: true })], []));
            compare(session.webStartData.sites[0].pinned, true);
        }

        function test_disableHistoryWhileSaving() {
            latest("/web/start").success(data([site], []));
            session.changeWebSite(site.location, "hide");
            const write = latest("/web/site");
            const before = data([site], []);
            session.ui = Object.assign({}, session.ui, { search_history: false });
            latest("/web/start").success(data([], []));
            write.success(before);
            compare((session.webStartData.sites || []).length, 0);
        }
    }
}
