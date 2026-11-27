// SPDX-License-Identifier: MIT
import QtQuick
import QtTest
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui" as HappyBot

Item {
    width: 650
    height: 470
    function i18n(text, value) { return value === undefined ? text : text.replace("%1", value); }

    QtObject {
        id: page
        property var settings: ({agent: { instructions: "Custom", remembered_facts: ["Keep tea hot"] }})
        property var last: null
        property var client: QtObject {
            function request(method, path, body, success, failure) {
                if (method === "GET") {
                    success({facts: page.settings.agent.remembered_facts});
                    return;
                }
                page.last = body;
                const update = page.settings.agent.remembered_facts.filter(fact => fact !== body.old);
                if (body.action !== "delete") update.push(body.fact);
                page.settings = {agent: {instructions: "Custom", remembered_facts: update}};
                success({settings: page.settings});
            }
        }
        function report(text, error) {}
    }

    HappyBot.RememberedFacts {
        id: facts
        width: parent.width
        page: page
        instructionsSaved: true
    }

    TestCase {
        name: "RememberedFacts"
        when: windowShown
        function test_searchKeyboardSaveAndDeleteConfirmation() {
            const search = findChild(facts, "rememberedFactsSearch");
            const entry = findChild(facts, "rememberedFactEntry");
            search.forceActiveFocus();
            keyClick(Qt.Key_Z);
            compare(facts.shown.length, 0);
            search.clear();
            compare(facts.shown[0], "Keep tea hot");
            entry.forceActiveFocus();
            keyClick(Qt.Key_A);
            keyClick(Qt.Key_Return);
            compare(page.last.action, "add");
            compare(facts.shown.length, 2);
            const first = findChild(facts, "deleteRememberedFact");
            mouseClick(first);
            compare(page.last.action, "add");
            verify(facts.deleting.length > 0);
            const confirm = findChild(facts, "confirmRememberedFactDelete");
            mouseClick(confirm);
            compare(page.last.action, "delete");
            compare(facts.shown.length, 1);
        }
    }
}
