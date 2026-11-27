// SPDX-License-Identifier: MIT
import QtQuick
import QtTest
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui" as HappyBot

Item {
    width: 650
    height: 850
    function i18n(text, value) { return value === undefined ? text : text.replace("%1", value); }

    QtObject {
        id: page
        property var settings: ({agent: { instructions: "Custom", remembered_facts: [{text: "Keep tea hot", prompt: "", local_only: true}] }})
        property var last: null
        property var client: QtObject {
            function request(method, path, body, success, failure) {
                if (method === "GET") {
                    success({facts: page.settings.agent.remembered_facts});
                    return;
                }
                page.last = body;
                const update = page.settings.agent.remembered_facts.filter(fact => !body.old || fact.text !== body.old.text || fact.prompt !== body.old.prompt);
                if (body.action !== "delete") update.push({text: body.fact, prompt: body.prompt, local_only: body.local_only});
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
            const preferredName = findChild(facts, "rememberedFact-name");
            const privacy = findChild(facts, "rememberedFactPrivacy-name");
            const save = findChild(facts, "saveRememberedFact-name");
            tryVerify(() => privacy.x > preferredName.x && save.parent.x > privacy.x);
            preferredName.forceActiveFocus();
            keyClick(Qt.Key_K);
            keyClick(Qt.Key_Return);
            compare(page.last.prompt, "name");
            compare(page.last.local_only, true);
            const language = findChild(facts, "rememberedFactChoice-language");
            const units = findChild(facts, "rememberedFactChoice-units");
            verify(language.model.includes("Spanish"));
            verify(units.model.includes("Metric"));
            language.currentIndex = language.model.indexOf("Spanish");
            mouseClick(findChild(facts, "saveRememberedFact-language"));
            compare(page.last.fact, "Spanish");
            language.currentIndex = language.model.indexOf("French");
            mouseClick(findChild(facts, "saveRememberedFact-language"));
            compare(page.last.action, "edit");
            compare(page.last.fact, "French");
            compare(facts.facts.filter(fact => fact.prompt === "language").length, 1);
            const search = findChild(facts, "rememberedFactsSearch");
            const entry = findChild(facts, "rememberedFactEntry");
            search.forceActiveFocus();
            keyClick(Qt.Key_Z);
            compare(facts.shown.length, 0);
            search.clear();
            compare(facts.shown[0].text, "Keep tea hot");
            entry.forceActiveFocus();
            keyClick(Qt.Key_A);
            keyClick(Qt.Key_Return);
            compare(page.last.action, "add");
            compare(facts.shown.length, 2);
            const first = findChild(facts, "deleteRememberedFact");
            mouseClick(first);
            compare(page.last.action, "add");
            verify(facts.deleting !== null);
            const confirm = findChild(facts, "confirmRememberedFactDelete");
            mouseClick(confirm);
            compare(page.last.action, "delete");
            compare(facts.shown.length, 1);
        }
    }
}
