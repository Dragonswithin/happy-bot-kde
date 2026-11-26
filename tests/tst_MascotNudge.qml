// SPDX-License-Identifier: MIT
// Exercise the desktop nudge inside the shared panel and floating assistant view.
import QtQuick
import QtTest
import org.kde.plasma.components as PlasmaComponents3
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui" as HappyBot

Item {
    width: 800
    height: 700

    function i18n(message) { return message; }
    function i18np(single, plural, count) { return count === 1 ? single : plural; }
    function i18nc(context, message) { return message; }

    HappyBot.ResultsView {
        id: view
        session: HappyBot.AssistantSession { configuredUrl: "http://127.0.0.1:9" }
    }

    SignalSpy { id: asked; target: view; signalName: "askRequested" }
    SignalSpy { id: settings; target: view; signalName: "settingsRequested" }

    TestCase {
        name: "MascotNudge"
        when: windowShown

        property var card
        property var action

        function findItem(item, predicate) {
            if (predicate(item)) return item;
            for (const child of item.children) {
                const result = findItem(child, predicate);
                if (result) return result;
            }
            return null;
        }

        function initTestCase() {
            card = findItem(view, item => item instanceof HappyBot.MascotNudge);
            verify(card);
            action = findItem(card, item => item instanceof PlasmaComponents3.Button);
            verify(action);
        }

        function init() {
            asked.clear();
            settings.clear();
            view.clearInput();
            view.session.busy = false;
            view.session.needsSetup = false;
            view.session.listening = false;
            view.session.pendingApprovals = 0;
            view.session.nudges = ["battery", "updates"];
        }

        function test_onlyClickingAsksForHelp() {
            verify(card.visible);
            compare(card.kind, "battery");
            verify(action.visible);
            compare(asked.count, 0);
            mouseClick(action);
            compare(asked.count, 1);
            compare(asked.signalArguments[0][0], card.suggestion.prompt);
            verify(asked.signalArguments[0][0].includes("power saver"));
            compare(settings.count, 0);
        }

        function test_withoutAModelOpensSetup() {
            view.session.needsSetup = true;
            verify(action.visible);
            compare(action.text, "Set up an AI…");
            mouseClick(action);
            compare(settings.count, 1);
            compare(asked.count, 0);
        }

        function test_conditionsWaitUntilTheUserIsFree() {
            view.setInput("Keep this draft");
            view.session.nudges = ["disk"];
            verify(!card.visible);
            compare(card.height, 0);
            compare(view.inputText, "Keep this draft");
            view.clearInput();
            verify(card.visible);
            for (const property of ["busy", "listening", "pendingApprovals"]) {
                view.session[property] = property === "pendingApprovals" ? 1 : true;
                verify(!card.visible);
                compare(card.height, 0);
                view.session[property] = property === "pendingApprovals" ? 0 : false;
                verify(card.visible);
            }
            view.session.nudges = [];
            verify(!card.visible);
            compare(asked.count, 0);
        }
    }
}
