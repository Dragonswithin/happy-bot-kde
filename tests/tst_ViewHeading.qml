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
            property var savedTasks: [{id: "1", text: "Existing task", group: "Home", due: "", done: false,
                                      priority: "none", repeat: "none", parent: "", reminder: ""}]
            property var taskPayload: null
            property int programRequests: 0
            property string lastProgramPath: ""
            function request(method, path, body, success, failure) {
                if (path.startsWith("/context/usage")) {
                    const model = path.endsWith("model=Wide") ? "Wide" : "Local";
                    success({context_usage: {model: model, used: 700,
                        capacity: model === "Wide" ? 8192 : 4096, estimated: true}});
                } else if (path === "/conversation?id=context-test") {
                    success({id: "context-test", model: "Local", events: [],
                        context_usage: {model: "Local", used: 3300, capacity: 4096, estimated: false}});
                } else if (path === "/tasks") {
                    if (method === "POST") {
                        taskPayload = body;
                        savedTasks = savedTasks.map(task => task.id === body.id ? Object.assign({}, task, body) : task);
                    }
                    success({tasks: savedTasks});
                } else if (path === "/system/overview") {
                    success({cpu: {model: "Test CPU", cores: 8, percent: 25, load: []},
                        memory: {used: 100, total: 200}, history: {cpu: [20, 25], memory: [50, 50], receive: [50, 80], send: [20, 40], gpu: {test: [3, 7]}, disk: [42, 61]},
                        gpus: [{id: "test", name: "Test GPU", busy_percent: 7, memory_used: 25, memory_total: 50, shared_used: 0, shared_total: 75}], network: {interface: "eth0"}, disks: [{mount: "/", total: 200, used: 100}],
                        hardware: {model: "Test workstation", board: "Test board", drives: [{device: "/dev/sda", model: "Test drive", total: 200, rotational: 0}]},
                        os: {name: "Test Linux", logo: "test-linux", version: "1", kernel: "6.0", architecture: "x86_64", desktop: "KDE", session: "wayland"},
                        uptime_seconds: 4500, last_restart: "reboot"});
                } else if (path.startsWith("/system/programs?")) {
                    programRequests++;
                    lastProgramPath = path;
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
            view.historyOpen = false;
            view.clearInput();
            session.chatDrafts = {};
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
            waitForRendering(view);
            mouseClick(picker);
            tryVerify(() => picker.popup.visible);
            keyClick(Qt.Key_Down);
            keyClick(Qt.Key_Return);
            tryCompare(session, "chatModel", "Local AI");
            compare(picker.displayText, "Local AI");
        }

        function test_contextMeterTracksProviderFallbackAndModelSelection() {
            session.models = [{name: "Local", context_window: 4096}, {name: "Unknown", context_window: 0},
                              {name: "Wide", context_window: 8192}];
            const meter = findChild(view, "assistantContextMeter");
            session.applyEvent({type: "context_usage", model: "Local", used: 800, estimated: true});
            verify(meter.visible && meter.detail.includes("Estimated"));
            session.applyEvent({type: "context_usage", model: "Local", used: 3700, estimated: false});
            verify(meter.nearLimit);
            verify(meter.detail.includes("Provider reported"));
            meter.forceActiveFocus(Qt.TabFocusReason);
            keyClick(Qt.Key_Space);
            verify(meter.checked);
            meter.checked = false;
            session.applyEvent({type: "context_usage", model: "Unknown", used: 8000, estimated: false});
            verify(!meter.nearLimit);
            verify(meter.detail.includes("capacity unavailable"));
            session.chatModel = "Wide";
            compare(meter.capacity, 8192);
            compare(meter.used, 700);
            session.openConversation("context-test");
            compare(meter.capacity, 4096);
            compare(meter.used, 3300);
            verify(meter.nearLimit);
            session.resetTranscript();
            compare(meter.used, 700);
            verify(!meter.nearLimit);
        }

        function test_tasksScreenEditsSharedTask() {
            session.showTasks();
            compare(heading.text, "Tasks");
            const tasks = findChild(view, "assistantTasks");
            tryCompare(tasks, "visible", true);
            tryCompare(tasks, "tasks", session.savedTasks);
            tasks.edit(tasks.tasks[0]);
            const title = findChild(tasks, "taskTitle");
            tryCompare(title, "activeFocus", true);
            keyClick(Qt.Key_A, Qt.ControlModifier);
            keyClick(Qt.Key_E);
            keyClick(Qt.Key_Return);
            tryCompare(tasks, "draft", null);
            compare(session.taskPayload.action, "edit");
            compare(session.taskPayload.text.toLowerCase(), "e");
            tryVerify(() => button(view, "Back").visible);
            mouseClick(button(view, "Back"));
            tryCompare(heading, "text", "Start screen");
        }

        function test_systemInfoOpensCardsThenDetails() {
            session.showSystemInfo();
            const processor = findChild(view, "systemCard-cpu");
            const memory = findChild(view, "systemCard-memory");
            const hardware = findChild(view, "systemCard-hardware");
            tryVerify(() => processor.visible && hardware.visible);
            compare(processor.expanded, false);
            for (const section of ["cpu", "memory", "network", "gpu-0", "disk-activity"]) {
                const chart = findChild(view, "systemGraph-" + section);
                verify(chart && chart.visible);
            }
            verify(memory.visible);
            tryVerify(() => Math.abs(processor.width - processor.height) <= 1);
            const activity = findChild(view, "systemCard-disk-activity");
            verify(activity && activity.visible && activity !== hardware);
            verify(!findChild(view, "systemGraph-hardware").visible);
            compare(session.programRequests, 0);
            compare(findChild(view, "systemCard-uptime").uptimeFraction, 4500 / 86400);
            waitForRendering(view);
            verify(hardware.iconSummary);
            compare(findChild(view, "systemIcon-hardware").source, "cpu");
            hardware.forceActiveFocus(Qt.TabFocusReason);
            keyClick(Qt.Key_Return);
            tryCompare(hardware, "expanded", true);
            verify(!hardware.iconSummary);
            verify(hardware.detail.includes("Test board"));
            verify(findChild(view, "systemCard-storage") === null);
            compare(processor.visible, false);
            compare(session.programRequests, 0);
            mouseClick(button(view, "Back"));
            tryCompare(processor, "visible", true);
            const network = findChild(view, "systemCard-network");
            network.forceActiveFocus(Qt.TabFocusReason);
            keyClick(Qt.Key_Return);
            tryCompare(network, "expanded", true);
            compare(findChild(view, "systemGraph-network").values[1], 80);
            compare(findChild(view, "systemGraph-network-upload").values[1], 40);
            mouseClick(button(view, "Back"));
            tryCompare(processor, "visible", true);
            const uptime = findChild(view, "systemCard-uptime");
            uptime.forceActiveFocus(Qt.TabFocusReason);
            keyClick(Qt.Key_Return);
            tryCompare(uptime, "expanded", true);
            verify(uptime.detail.includes("Orderly reboot"));
            mouseClick(button(view, "Back"));
            tryCompare(processor, "visible", true);
            const os = findChild(view, "systemCard-os");
            verify(os && os.visible && os.iconSummary);
            compare(findChild(view, "systemIcon-os").source, "test-linux");
            os.forceActiveFocus(Qt.TabFocusReason);
            keyClick(Qt.Key_Return);
            tryCompare(os, "expanded", true);
            verify(!os.iconSummary);
            verify(os.detail.includes("6.0"));
            mouseClick(button(view, "Back"));
            tryCompare(processor, "visible", true);
            waitForRendering(view);
            mouseClick(processor);
            tryCompare(processor, "expanded", true);
            tryVerify(() => session.programRequests > 0);
            tryCompare(session, "lastProgramPath", "/system/programs?sort=cpu&order=desc");
            mouseClick(findChild(view, "systemSort-memory"));
            tryCompare(session, "lastProgramPath", "/system/programs?sort=memory&order=desc");
            mouseClick(findChild(view, "systemSort-memory"));
            tryCompare(session, "lastProgramPath", "/system/programs?sort=memory&order=asc");
            mouseClick(findChild(view, "systemSort-user"));
            tryCompare(session, "lastProgramPath", "/system/programs?sort=user&order=asc");
            mouseClick(button(view, "Back"));
            tryCompare(memory, "visible", true);
            waitForRendering(view);
            mouseClick(memory);
            tryCompare(memory, "expanded", true);
            verify(memory.detail.includes("System RAM available"));
            const vram = findChild(view, "memoryVram");
            const shared = findChild(view, "memorySharedGpu");
            verify(vram.visible && shared.visible);
            compare(vram.used, 25);
            compare(shared.used, 0);
            verify(shared.totalLabel.includes("driver limit"));
            tryCompare(session, "lastProgramPath", "/system/programs?sort=memory&order=desc");
            mouseClick(button(view, "Back"));
            tryCompare(hardware, "visible", true);
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

        function test_reopenAndResumeDraft() {
            session.conversationId = "a";
            session.history = [{id: "a", title: "Storage", updated: 1}];
            session.appendEntry("user", "Check storage");
            view.setInput("And the second disk?");
            view.closingPopup();
            view.popupHidden();
            view.hiddenAt = 1000;
            view.prepareOpen(5000);
            compare(heading.text, "Storage");
            compare(view.inputText, "And the second disk?");
            view.hiddenAt = 5000;
            view.prepareOpen(36000);
            compare(heading.text, "Start screen");
            compare(view.inputText, "");
            waitForRendering(view);
            mouseClick(button(view, "Previous chats"));
            wait(250);
            mouseClick(findChild(view, "conversation-a"));
            compare(heading.text, "Storage");
            compare(view.inputText, "And the second disk?");
            view.parkChat();
            compare(heading.text, "Start screen");
            compare(session.entries.count, 1);
            session.busy = true;
            view.resumeChat("a");
            verify(session.busy);
            session.busy = false;
        }

        function test_drawerSelectSavedChatWithoutSending() {
            session.history = [{id: "pinned", title: "Older", updated: 1},
                               {id: "context-test", title: "Most recent", updated: 2}];
            compare(view.drawerChats.length, 2);
            verify(!view.sidebarVisible);
            verify(!findChild(view, "conversationDrawer").visible);
            const width = view.width;
            mouseClick(button(view, "Previous chats"));
            verify(view.sidebarVisible);
            wait(250);
            compare(view.width, width);
            view.popupHidden();
            view.prepareOpen(Date.now());
            verify(!findChild(view, "conversationDrawer").visible);
            mouseClick(button(view, "Previous chats"));
            wait(250);
            mouseClick(findChild(view, "conversation-context-test"));
            compare(session.conversationId, "context-test");
            verify(!view.sidebarVisible);
            verify(!session.busy);
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
