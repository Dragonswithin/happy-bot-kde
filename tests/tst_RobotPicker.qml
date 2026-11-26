// SPDX-License-Identifier: MIT
import QtQuick
import QtTest
import org.kde.kirigami as Kirigami
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui" as HappyBot

Item {
    id: view
    width: 600
    height: 500

    function i18n(text) { return text; }

    HappyBot.RobotPicker {
        id: picker
        width: parent.width
        useRobotMascot: true
        robotStyle: "pip"
        property var changes: []
        onChoiceRequested: change => {
            picker.changes.push(change);
            if (change.robot_mascot !== undefined) picker.useRobotMascot = change.robot_mascot;
            if (change.robot_style !== undefined) picker.robotStyle = change.robot_style;
            if (change.sounds_follow_mascot !== undefined) picker.soundsFollowMascot = change.sounds_follow_mascot;
        }
    }

    TestCase {
        name: "RobotPicker"
        when: windowShown

        readonly property var ids: [
            "pip", "rivet", "orbit", "watt", "pixel", "sprig", "nixie", "sprocket", "sonar", "dotty"
        ]

        function tile(id) { return findChild(picker, "robot-" + id); }

        function init() {
            picker.useRobotMascot = true;
            picker.robotStyle = "pip";
            picker.soundsFollowMascot = true;
            picker.width = view.width;
            picker.changes = [];
            waitForPolish(picker);
        }

        function test_namedRobotsAreSelectable() {
            const sources = [];
            for (const id of ids) {
                const choice = tile(id);
                verify(choice);
                verify(choice.visible);
                verify(choice.Accessible.name.length > 0);
                const image = choice.contentItem.children.find(child => child instanceof Image);
                verify(image);
                tryCompare(image, "status", Image.Ready);
                const source = image.source.toString();
                compare(source, HappyBot.Look.robotImage(id).toString());
                verify(!sources.includes(source), id + " has its own portrait");
                sources.push(source);
                mouseClick(choice);
                compare(picker.robotStyle, id);
                compare(ids.filter(item => tile(item).checked), [id]);
            }
            compare(picker.changes.length, ids.length - 1);  // Pip was already selected.
        }

        function test_wandIsAThemeAndExistingSelectionIsRecognized() {
            picker.useRobotMascot = false;
            picker.robotStyle = "sonar";
            verify(tile("wand").checked);
            verify(tile("sonar").visible && !tile("sonar").checked);
            mouseClick(tile("sonar"));
            compare(picker.changes[0], {robot_mascot: true, robot_style: "sonar"});
            mouseClick(tile("wand"));
            compare(picker.changes[1], {robot_mascot: false});
            compare(picker.robotStyle, "sonar");
            verify(tile("wand").checked);
        }

        function test_soundCheckboxIsOnInitiallyAndCanBeClearedBeforeChoosing() {
            const follow = findChild(picker, "followMascotSounds");
            verify(follow.checked);
            mouseClick(follow);
            compare(picker.changes[0], {sounds_follow_mascot: false});
            mouseClick(tile("dotty"));
            compare(picker.robotStyle, "dotty");
            verify(!follow.checked);
        }

        function test_keyboardFollowsColumnsWhenNarrowOrWide() {
            const pip = tile("pip");
            const orbit = tile("orbit");
            picker.width = 11 * Kirigami.Units.gridUnit;
            tryVerify(() => orbit.y > pip.y);
            pip.forceActiveFocus(Qt.TabFocusReason);
            keyClick(Qt.Key_Down);
            compare(picker.robotStyle, "orbit");
            verify(orbit.activeFocus);

            picker.width = view.width;
            tryVerify(() => orbit.y === pip.y);
            keyClick(Qt.Key_Right);
            compare(picker.robotStyle, "watt");
            keyClick(Qt.Key_End);
            compare(picker.selectedTheme, "wand");
            verify(tile("wand").activeFocus);
        }
    }
}
