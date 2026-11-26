// SPDX-License-Identifier: MIT
import QtQuick
import QtTest
import org.kde.kirigami as Kirigami
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
            property int programRequests: 0
            function request(method, path, body, success, failure) {
                if (path === "/system/overview") {
                    success({cpu: {model: "Test CPU", cores: 8, percent: 25, load: []},
                        memory: {used: 100, total: 200}, history: {cpu: [20, 25], memory: [50, 50], receive: [50, 80], gpu: {test: [3, 7]}, disk: [42, 61]},
                        gpus: [{id: "test", name: "Test GPU", busy_percent: 7}], network: {interface: "eth0"}, disks: [{mount: "/", total: 200, used: 100}],
                        uptime_seconds: 4500});
                } else if (path.startsWith("/system/programs?")) {
                    programRequests++;
                    success({programs: []});
                }
            }
        }
    }

    HappyBot.PanelResults {
        id: panelResults
        session: view.session
        useRobotMascot: view.useRobotMascot
    }

    SignalSpy { id: moves; target: view; signalName: "windowMoved" }
    SignalSpy { id: closes; target: view; signalName: "closeRequested" }

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
            view.windowPosition = null;
            view.fieldAtBottom = false;
            session.stopFinding();
            session.stopFixing();
            session.resetTranscript();
            session.history = [];
            session.models = [];
            session.chatModel = "";
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
            const cases = [];
            for (const saved of [false, true])
                for (const text of ["Find a file", "Search the web", "System info", "Desktop help"])
                    cases.push({ tag: text + (saved ? " with sidebar" : ""), text, saved });
            return cases;
        }

        function test_startScreenTiles(data) {
            view.useRobotMascot = true;
            view.fieldAtBottom = data.saved;
            session.history = data.saved ? [{ id: "a", title: "Saved chat", updated: 0 }] : [];
            const width = view.width;
            compare(heading.text, "Start screen");
            const surface = view.gradient;
            verify(surface !== null);
            tryVerify(() => !!button(view, data.text));
            waitForRendering(view);
            mouseClick(button(view, data.text));
            tryCompare(heading, "text", data.text);
            compare(view.gradient, surface);
            compare(view.width, width);
            compare(view.height, view.heightInGridUnits * Kirigami.Units.gridUnit);
            waitForRendering(view);
            const back = button(view, "Back");
            const position = back.mapToItem(view, 0, 0);
            verify(position.x < Kirigami.Units.gridUnit * 2);
            verify(position.y + back.height >= view.height - Kirigami.Units.gridUnit * 1.5);
            mouseClick(back);
            tryCompare(heading, "text", "Start screen");
        }

        function test_backgroundDragsButControlsStayClickable() {
            view.windowPosition = () => Qt.point(40, 80);
            moves.clear();
            closes.clear();
            verify(!button(view, "Settings"));
            mouseDrag(view, 8, view.height - 11, 45, -5);
            compare(moves.count, 1);
            compare(moves.signalArguments[0][0], Qt.point(85, 75));

            moves.clear();
            mouseDrag(view, Math.round(view.width / 2), 55, 45, 0);
            compare(moves.count, 0);
            mouseClick(button(view, "Close (Esc)"));
            compare(closes.count, 1);
        }

        function test_panelAndToolsShareEachMascotPalette() {
            view.useRobotMascot = true;
            session.voiceEnabled = true;
            const mic = findChild(view, "themedMicrophone");
            verify(mic && mic.visible);
            const colors = new Set();
            for (const design of HappyBot.Look.robotStyles) {
                session.ui = Object.assign({}, session.ui, {robot_style: design.id});
                compare(view.accent, Qt.color(design.accent));
                compare(mic.accent, view.accent);
                compare(panelResults.mainItem.accent, view.accent);
                compare(panelResults.mainItem.gradient.stops[1].color, view.gradient.stops[1].color);
                colors.add(String(view.accent));
            }
            compare(colors.size, 10);
            session.listening = true;
            verify(mic.recording);
            session.listening = false;
            session.voiceEnabled = false;
            view.useRobotMascot = false;
            compare(panelResults.mainItem.accent, view.accent);
            verify(view.nativeLook && panelResults.mainItem.nativeLook && mic.nativeLook);
            compare(view.gradient, null);
            session.ui = Object.assign({}, session.ui, {robot_style: "pip"});
        }

        function test_modelSelector() {
            session.models = [{name: "Local AI"}, {name: "Hosted AI", online: true}];
            const picker = findChild(view, "chatModelPicker");
            tryVerify(() => picker.visible);
            tryVerify(() => picker.width > 0);
            mouseClick(picker);
            tryVerify(() => picker.popup.visible);
            keyClick(Qt.Key_Down);
            keyClick(Qt.Key_Return);
            tryCompare(session, "chatModel", "Local AI");
            compare(picker.displayText, "Local AI");
        }

        function test_systemInfoOpensCardsThenDetails() {
            session.showSystemInfo();
            const processor = findChild(view, "systemCard-cpu");
            const storage = findChild(view, "systemCard-storage");
            tryVerify(() => processor.visible && storage.visible);
            compare(processor.expanded, false);
            for (const section of ["cpu", "memory", "network", "gpu-0", "storage"]) {
                const chart = findChild(view, "systemGraph-" + section);
                verify(chart && chart.visible);
            }
            tryVerify(() => Math.abs(processor.width - processor.height) <= 1);
            compare(session.programRequests, 0);
            compare(findChild(view, "systemCard-uptime").uptimeFraction, 4500 / 86400);
            waitForRendering(view);
            mouseClick(storage);
            tryCompare(storage, "expanded", true);
            compare(processor.visible, false);
            compare(session.programRequests, 0);
            mouseClick(button(view, "Back"));
            tryCompare(processor, "visible", true);
            waitForRendering(view);
            mouseClick(processor);
            tryCompare(processor, "expanded", true);
            tryVerify(() => session.programRequests > 0);
            mouseClick(button(view, "Back"));
            tryCompare(storage, "visible", true);
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
