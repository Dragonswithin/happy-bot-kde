// SPDX-License-Identifier: MIT
import QtQuick
import QtTest
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui" as HappyBot

Item {
    id: root
    width: 520
    height: 610

    function i18n(text, first, second) {
        return String(text).replace("%1", first).replace("%2", second);
    }

    HappyBot.FileResults {
        id: view
        anchors.fill: parent
        query: "plasma"
        session: QtObject {
            property string finder: "web"
            property bool showingRecent: false
            property string searchError: ""
            property string searchErrorCode: ""
            property bool finding: true
            property bool searching: false
            property string searchedText: "plasma"
            property var webStartData: ({ sites: [{host: "kde.org", pinned: true}] })
            property var hits: [
                {kind: "quick", title: "Plasma handbook", subtitle: "Bookmark · docs.kde.org · Firefox",
                 icon: "bookmarks", site_host: "docs.kde.org", action: {type: "bookmark", target: "https://docs.kde.org/plasma"}},
                {kind: "quick", title: "Plasma", subtitle: "Visited · kde.org · Chromium", icon: "internet-web-browser",
                 site_host: "kde.org", action: {type: "visited", target: "https://www.kde.org/plasma-desktop/"}},
                {kind: "link", title: "Plasma news", location: "https://www.kde.org/news/", source: "web", site_host: "kde.org",
                 snippet: "News about the Plasma desktop. ".repeat(12)},
                {kind: "article", source: "wikipedia", title: "Plasma", location: "Plasma", snippet: "An article in Wikipedia."}
            ]
            property var lastChange: null
            function changeWebSite(url, action) { lastChange = {url, action}; }
        }
    }
    SignalSpy { id: links; target: view; signalName: "fileActionRequested" }
    SignalSpy { id: opens; target: view; signalName: "resultActivated" }

    TestCase {
        name: "WebResultSites"
        when: windowShown
        function row(index) { return findChild(view, "resultRow-" + index); }
        function menu() { return findChild(view, "webResultMenu"); }
        function childWithText(item, text) {
            if (item.text === text && item.visible) return item;
            for (const child of item.children) {
                const match = childWithText(child, text);
                if (match) return match;
            }
            return null;
        }
        function init() {
            view.session.finder = "web";
            view.session.lastChange = null;
            view.selectedIndex = -1;
            links.clear();
            opens.clear();
            waitForRendering(view);
        }

        function test_rightClickBookmarkPin() {
            mouseClick(row(0), 14, 14, Qt.RightButton);
            tryCompare(menu(), "opened", true);
            compare(menu().itemAt(0).text, "Pin site");
            mouseClick(menu().itemAt(0));
            compare(view.session.lastChange, { url: view.session.hits[0].action.target, action: "pin" });
            compare(opens.count, 0);
        }

        function test_keyboardVisitedAndWebActions() {
            view.selectedIndex = 1;
            view.openSelectedMenu();
            tryCompare(menu(), "opened", true);
            compare(menu().itemAt(0).text, "Unpin site");
            mouseClick(menu().itemAt(1));
            compare(view.session.lastChange, { url: view.session.hits[1].action.target, action: "hide" });
            tryCompare(menu(), "visible", false);
            view.selectedIndex = 2;
            view.openSelectedMenu();
            tryCompare(menu(), "opened", true);
            const copy = childWithText(menu().contentItem, "Copy link");
            verify(!!copy);
            mouseClick(copy);
            compare(links.count, 1);
            compare(links.signalArguments[0][0].location, "https://www.kde.org/news/");
            compare(links.signalArguments[0][1], "copy");
        }

        function test_webSnippetWrapsAndWikiRetainsItsOwnDetail() {
            verify(!!childWithText(row(2), "kde.org"));
            const snippet = childWithText(row(2), view.session.hits[2].snippet);
            verify(!!snippet);
            compare(snippet.maximumLineCount, 2);
            compare(snippet.lineCount, 2);
            verify(!!childWithText(row(3), "An article in Wikipedia."));
            mouseClick(row(3));
            compare(opens.signalArguments[0][0].kind, "article");
        }

        function test_bookmarkInTheFileFinderHasItsUsualRow() {
            view.session.finder = "files";
            view.selectedIndex = 0;
            view.openSelectedMenu();
            verify(!menu().visible);
            verify(!!childWithText(row(0), "docs.kde.org · Firefox"));
        }
    }
}
