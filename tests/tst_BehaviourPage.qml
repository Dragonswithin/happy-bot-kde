// SPDX-License-Identifier: MIT
// Checks two layout mistakes on the Behaviour settings page (SetupBehavior.qml) that once made it
// unusable:
// - Its two sets of choices, "Ask before it" (approval_policy) and "The app you're in"
//   (agent.app_context), must be separate. Qt Quick radio buttons with the same parent are one
//   exclusive set unless given a ButtonGroup, and every row of the page is a child of its form,
//   so the two once acted as one and choosing one setting cleared the other.
// - The "Your instructions" box must keep its height when the text is long and scroll inside,
//   with the character count below it: it once grew with the text and drew it over the count
//   and the buttons.
// The page is given a stand-in settings dialog (`page`) whose save does nothing. Run with the Qt 6
// runner:
//   /usr/lib/qt6/bin/qmltestrunner -input tests/tst_BehaviourPage.qml
import QtQuick
import QtQuick.Controls as QQC2
import QtTest
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui" as HappyBot

Item {
    width: 600
    height: 1600

    // Plasma supplies i18n in the applet's context.
    function i18n(message) { return message; }
    function i18np(single, plural, count) { return count === 1 ? single : plural; }

    HappyBot.SetupBehavior {
        id: behaviour
        page: ({
            terminals: [], suggestedInstructions: "", save: function(change) {},
            settings: { approval_policy: "danger", agent: {
                app_context: "local", local_only: false, notify_after_seconds: 60, max_steps: 20,
                command_timeout_seconds: 60, disabled_tool_groups: [], instructions: "", terminal: "" } }
        })
    }

    TestCase {
        name: "BehaviourPage"
        when: windowShown

        function radios(item, found) {
            for (const child of item.children) {
                if (child instanceof QQC2.RadioButton) found.push(child);
                radios(child, found);
            }
            return found;
        }

        function find(item, test) {
            if (test(item)) return item;
            for (const child of item.children) {
                const found = find(child, test);
                if (found) return found;
            }
            return null;
        }

        function test_longInstructionsScrollInsideTheirBox() {
            const editor = find(behaviour, item => item instanceof QQC2.TextArea);
            const box = find(behaviour, item => item instanceof QQC2.ScrollView);
            const count = find(behaviour, item => item instanceof QQC2.Label && item.text.indexOf("4000") >= 0);
            verify(editor && box && count);
            const height = box.height;
            editor.text = "A standing preference that wraps over more than one line of the box.\n".repeat(40);
            tryVerify(() => editor.implicitHeight > height * 2);
            compare(box.height, height);
            verify(count.mapToItem(behaviour, 0, 0).y >= box.mapToItem(behaviour, 0, 0).y + box.height,
                   "the character count is below the box");
        }

        function test_eachSettingKeepsItsOwnChoice() {
            const buttons = radios(behaviour, []);
            compare(buttons.length, 6);   // three approval choices, then three app-context choices
            const checked = () => buttons.map(button => button.checked);
            compare(checked(), [true, false, false, true, false, false]);
            buttons[4].toggle();          // "Any AI may see it"
            compare(checked(), [true, false, false, false, true, false]);
            buttons[1].toggle();          // "Changes anything at all"
            compare(checked(), [false, true, false, false, true, false]);
        }
    }
}
