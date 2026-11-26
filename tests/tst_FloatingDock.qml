// SPDX-License-Identifier: MIT
import QtQuick
import QtTest
import org.kde.layershell as LayerShell
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui" as HappyBot

Item {
    function i18n(message) { return message; }
    function i18np(single, plural, count) { return count === 1 ? single : plural; }
    function i18nc(context, message) { return message; }

    HappyBot.FloatingButton {
        id: shortcut
        session: HappyBot.AssistantSession { configuredUrl: "http://127.0.0.1:9" }
        activity: HappyBot.IconActivity {}
        useRobotMascot: true
        onClicked: open()
        onMenuRequested: menuOpen = true
        onMoved: (x, y) => { posX = x; posY = y; }
    }

    SignalSpy { id: clicks; target: shortcut; signalName: "clicked" }
    SignalSpy { id: menus; target: shortcut; signalName: "menuRequested" }
    SignalSpy { id: moves; target: shortcut; signalName: "moved" }

    TestCase {
        name: "FloatingDock"
        when: windowShown

        function setMode(docked, percent) {
            shortcut.session.ui = Object.assign({}, shortcut.session.ui, {
                floating_docked: docked, floating_size: percent
            });
        }

        function leave() {
            mouseMove(shortcut.contentItem, -15, -15);
        }

        function leftMargin() {
            const layer = shortcut.LayerShell.Window;
            return layer.anchors & LayerShell.Window.AnchorRight
                ? shortcut.screenWidth - shortcut.width - layer.margins.right : layer.margins.left;
        }

        function init() {
            shortcut.close();
            shortcut.session.showingSystem = false;
            shortcut.popupPosition = Qt.point(-1, -1);
            shortcut.heightInGridUnits = 26;
            shortcut.menuOpen = false;
            leave();
            setMode(false, 100);
            tryCompare(shortcut, "width", shortcut.size);
            clicks.clear();
            menus.clear();
            moves.clear();
        }

        function test_expandsFromOneEdge_data() {
            return [{tag: "room-above", top: 160, up: true},
                    {tag: "near-screen-top", top: 10, up: false}];
        }

        function test_expandsFromOneEdge(data) {
            shortcut.heightInGridUnits = 22;
            shortcut.popupPosition = Qt.point(20, data.top);
            shortcut.open();
            tryCompare(shortcut, "height", shortcut.openHeight);
            const initialHeight = shortcut.height;
            compare(shortcut.screenPosition.y, data.top);

            shortcut.session.showingSystem = true;
            tryVerify(() => shortcut.height > initialHeight);
            if (data.up)
                tryVerify(() => shortcut.screenPosition.y + shortcut.height === data.top + initialHeight);
            else
                compare(shortcut.screenPosition.y, data.top);

            shortcut.session.showingSystem = false;
            tryCompare(shortcut, "height", initialHeight);
            tryVerify(() => shortcut.screenPosition.y === data.top);
        }

        function test_hoverAndRetract_data() {
            return [
                { tag: "left-small", right: false, percent: 50 },
                { tag: "right", right: true, percent: 100 },
                { tag: "right-large", right: true, percent: 200 }
            ];
        }

        function test_hoverAndRetract(data) {
            shortcut.posX = Math.round(shortcut.screenWidth * (data.right ? 0.7 : 0.2));
            shortcut.posY = 100;
            setMode(true, data.percent);
            tryVerify(() => shortcut.width <= 12 && shortcut.height < shortcut.size);
            const tabWidth = shortcut.width;
            const tabHeight = shortcut.height;
            verify(tabWidth > 0 && tabHeight > tabWidth);
            tryVerify(() => leftMargin() === (data.right ? shortcut.screenWidth - tabWidth : 0));
            tryVerify(() => Math.abs(shortcut.LayerShell.Window.margins.top + tabHeight / 2
                                    - shortcut.posY - shortcut.size / 2) <= 0.5);

            mouseMove(shortcut.contentItem, Math.floor(tabWidth / 2), Math.floor(tabHeight / 2));
            tryCompare(shortcut, "width", shortcut.size);
            tryCompare(shortcut, "height", shortcut.size);
            tryVerify(() => leftMargin() === (data.right ? shortcut.screenWidth - shortcut.size : 0));
            tryVerify(() => shortcut.LayerShell.Window.margins.top === shortcut.posY);
            verify(!shortcut.expanded);

            mouseClick(shortcut.contentItem, shortcut.size / 2, shortcut.size / 2, Qt.RightButton);
            compare(menus.count, 1);
            compare(clicks.count, 0);
            leave();
            wait(500);
            compare(shortcut.width, shortcut.size);
            shortcut.menuOpen = false;
            tryCompare(shortcut, "width", tabWidth);
            compare(shortcut.height, tabHeight);
            compare(moves.count, 0);

            setMode(false, data.percent);
            tryCompare(shortcut, "width", shortcut.size);
            tryVerify(() => leftMargin() === shortcut.posX);
            tryVerify(() => shortcut.LayerShell.Window.margins.top === shortcut.posY);
        }

        function test_dragAcrossDesktopSnapsToOtherEdge() {
            shortcut.posX = 20;
            shortcut.posY = 70;
            setMode(true, 100);
            tryVerify(() => shortcut.width <= 12);
            const tabWidth = shortcut.width;
            mouseMove(shortcut.contentItem, tabWidth / 2, shortcut.height / 2);
            tryCompare(shortcut, "width", shortcut.size);
            const center = shortcut.size / 2;
            const offsetX = Math.round(shortcut.screenWidth * 0.7);
            mousePress(shortcut.contentItem, center, center);
            mouseMove(shortcut.contentItem, center + offsetX, center + 60, -1, Qt.LeftButton);
            // The layer surface follows the pointer, which is centered in the button again.
            mouseRelease(shortcut.contentItem, center, center);
            compare(moves.count, 1);
            compare(moves.signalArguments[0][0], offsetX);
            compare(moves.signalArguments[0][1], 130);
            compare(clicks.count, 0);
            leave();
            tryCompare(shortcut, "width", tabWidth);
            tryVerify(() => leftMargin() === shortcut.screenWidth - tabWidth);
        }

        function test_clickOpensAndLeavingKeepsAssistantOpen() {
            shortcut.posX = 30;
            shortcut.posY = 30;
            setMode(true, 100);
            tryVerify(() => shortcut.width <= 12);
            const tabWidth = shortcut.width;
            mouseMove(shortcut.contentItem, tabWidth / 2, shortcut.height / 2);
            tryCompare(shortcut, "width", shortcut.size);
            mouseClick(shortcut.contentItem, shortcut.width / 2, shortcut.height / 2);
            compare(clicks.count, 1);
            verify(shortcut.expanded);
            leave();
            tryCompare(shortcut, "width", shortcut.openWidth);
            tryCompare(shortcut, "height", shortcut.openHeight);
            shortcut.close();
            tryCompare(shortcut, "width", tabWidth);
        }
    }
}
