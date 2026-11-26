// SPDX-License-Identifier: MIT
import QtQuick
import QtTest
import org.kde.kirigami as Kirigami
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui" as HappyBot

Item {
    id: root
    width: 600
    height: 560
    function i18n(text, value) { return value === undefined ? text : text.replace("%1", value); }

    HappyBot.WebStartPage { id: page; width: parent.width; height: parent.height }
    SignalSpy { id: opened; target: page; signalName: "siteActivated" }
    SignalSpy { id: actions; target: page; signalName: "siteActionRequested" }
    SignalSpy { id: searched; target: page; signalName: "searchActivated" }
    SignalSpy { id: siteSearch; target: page; signalName: "siteSearchRequested" }

    TestCase {
        name: "WebStartPage"
        when: windowShown

        readonly property var addresses: ["example.org", "docs.example.org", "kde.org", "planet.example.org", "maps.example.org"]

        function tile(index) { return findChild(page, "webSite-" + addresses[index]); }
        function menu() { return findChild(page, "webSiteMenu"); }

        function init() {
            page.width = root.width;
            page.height = root.height;
            page.selectedIndex = -1;
            page.sites = addresses.map((host, index) => ({
                host, title: index === 0 ? "Example" : host, location: "https://" + host + "/", pinned: index === 1
            }));
            page.searches = ["keyboard shortcuts", "KDE panel settings"];
            page.historyEnabled = true;
            opened.clear();
            actions.clear();
            searched.clear();
            siteSearch.clear();
            waitForRendering(page);
        }

        function test_cachedFavicon() {
            const sites = page.sites.slice();
            sites[0].favicon = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGMwaDgAAAJUAXHIMWMAAAAAAElFTkSuQmCC";
            page.sites = sites;
            const icon = findChild(tile(0), "siteFavicon");
            tryCompare(icon, "status", Image.Ready);
            compare(findChild(tile(1), "siteFavicon").status, Image.Null);
        }

        function test_contextMenu() {
            mouseClick(tile(0), 15, 15, Qt.RightButton);
            tryCompare(menu(), "opened", true);
            compare(menu().itemAt(0).text, "Pin site");
            mouseClick(menu().itemAt(0));
            tryCompare(actions, "count", 1);
            compare(actions.signalArguments[0][0].host, addresses[0]);
            compare(actions.signalArguments[0][1], "pin");
            compare(opened.count, 0);
            tryCompare(menu(), "visible", false);

            tile(1).forceActiveFocus();
            keyClick(Qt.Key_F10, Qt.ShiftModifier);
            tryCompare(menu(), "opened", true);
            compare(menu().itemAt(0).text, "Unpin site");
            mouseClick(menu().itemAt(0));
            tryCompare(actions, "count", 2);
            compare(actions.signalArguments[1][1], "unpin");
            tryCompare(menu(), "visible", false);

            page.selectedIndex = 0;
            page.openSelectedMenu();
            tryCompare(menu(), "opened", true);
            mouseClick(menu().itemAt(1));
            tryCompare(actions, "count", 3);
            compare(actions.signalArguments[2][1], "hide");
            compare(opened.count, 0);
        }

        function test_clickAndRepeatSearch() {
            compare(page.itemCount, addresses.length + page.searches.length);
            mouseClick(tile(2));
            compare(opened.count, 1);
            compare(opened.signalArguments[0][0].host, addresses[2]);
            mouseClick(findChild(page, "webSearch-0"));
            compare(searched.signalArguments[0][0], "keyboard shortcuts");
            page.selectedIndex = addresses.length + 1;
            page.activateSelected();
            compare(searched.signalArguments[1][0], "KDE panel settings");
        }

        function test_searchPinnedSite() {
            page.selectedIndex = 1;
            page.openSelectedMenu();
            tryCompare(menu(), "opened", true);
            const search = menu().itemAt(3);
            compare(search.text, "Search this site");
            mouseClick(search);
            compare(siteSearch.count, 1);
            compare(siteSearch.signalArguments[0][0], addresses[1]);
            compare(opened.count, 0);
        }

        function test_narrowSelectionScrollsIntoView() {
            page.width = Kirigami.Units.gridUnit * 12;
            page.height = Kirigami.Units.gridUnit * 8;
            waitForRendering(page);
            tryVerify(() => tile(4).y > tile(0).y);
            verify(page.naturalHeight > page.height);
            page.selectedIndex = page.itemCount - 1;
            const last = findChild(page, "webSearch-1");
            tryVerify(() => last.mapToItem(page, 0, 0).y >= 0 && last.mapToItem(page, 0, last.height).y <= page.height + 1);
        }

        function test_emptyStartKeepsItsHeight() {
            page.sites = [];
            page.searches = [];
            page.historyEnabled = false;
            compare(page.itemCount, 0);
            verify(page.naturalHeight >= Kirigami.Units.gridUnit * 14);
        }
    }
}
