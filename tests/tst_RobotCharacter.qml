// SPDX-License-Identifier: MIT
// Exercise the motion switch mid-greeting as well as hover and visibility changes
// on the real rendered character, at the size of the floating shortcut.
import QtQuick
import QtTest
import org.kde.kirigami as Kirigami
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui" as HappyBot

Item {
    id: scene
    width: 120
    height: 56

    Item {
        id: surface
        x: 12
        anchors.verticalCenter: parent.verticalCenter
        width: 32
        height: 32
        HappyBot.RobotCharacter {
            id: robot
            anchors.fill: parent
            animate: false
        }
    }

    Image {
        id: original
        x: 72
        anchors.verticalCenter: parent.verticalCenter
        width: surface.width
        height: surface.height
        sourceSize.width: width
        sourceSize.height: height
        source: HappyBot.Look.robotIcon
    }

    TestCase {
        name: "RobotCharacter"
        when: windowShown

        function init() {
            robot.animate = false;
            robot.attentive = false;
            robot.greetOnShow = false;
            surface.visible = true;
            tryCompare(original, "status", Image.Ready);
            tryVerify(() => grabImage(surface).equals(grabImage(original)));
        }

        function enableMotion() {
            if (Kirigami.Units.longDuration <= 1) skip("Plasma animations are disabled");
            robot.animate = true;
            waitForPolish(robot);
        }

        // At shortcut scale the two gold lights are only a few pixels each.
        // Seeing the palm beside the head while the antenna is still above it
        // distinguishes the unfolded arm from rotating the resting icon.
        function hasGold(frame, left, top, right, bottom) {
            for (let y = Math.floor(top * frame.height); y < bottom * frame.height; y++) {
                for (let x = Math.floor(left * frame.width); x < right * frame.width; x++) {
                    const r = frame.red(x, y), g = frame.green(x, y), b = frame.blue(x, y);
                    if (r > 190 && g > 125 && b < 150 && r > 1.7 * b) return true;
                }
            }
            return false;
        }

        function test_motionOffShowsTheOriginalIcon() {
            const still = grabImage(original);
            robot.attentive = true;
            robot.greetOnShow = true;
            robot.greet();
            wait(120);
            verify(grabImage(surface).equals(still));
        }

        function test_hoverMovesThroughSeveralPosesInsideTheShortcut() {
            enableMotion();
            const idle = grabImage(surface);
            robot.attentive = true;
            tryVerify(() => {
                const frame = grabImage(surface);
                return hasGold(frame, 0.25, 0, 0.70, 0.29)
                    && hasGold(frame, 0.71, 0.24, 0.99, 0.55);
            });
            const firstPose = grabImage(surface);
            tryVerify(() => {
                const next = grabImage(surface);
                return !next.equals(firstPose) && !next.equals(idle);
            });
            compare(robot.mapToItem(surface, 0, 0), Qt.point(0, 0));
            compare(robot.mapToItem(surface, robot.width, robot.height), Qt.point(32, 32));

            robot.animate = false;
            tryVerify(() => grabImage(surface).equals(grabImage(original)));
        }

        function test_idleFaceMovesThenRestsWithoutHover() {
            enableMotion();
            const idle = grabImage(original);
            tryVerify(() => !grabImage(surface).equals(idle), 8000);
            tryVerify(() => grabImage(surface).equals(idle));
        }

        function test_portraitGreetsWhenShown() {
            enableMotion();
            const idle = grabImage(surface);
            surface.visible = false;
            robot.greetOnShow = true;
            surface.visible = true;
            tryVerify(() => !grabImage(surface).equals(idle));
        }

        function test_hidingCancelsGreetingAndReplayWorks() {
            enableMotion();
            const idle = grabImage(surface);
            robot.greet();
            tryVerify(() => !grabImage(surface).equals(idle));
            surface.visible = false;
            wait(30);
            surface.visible = true;
            tryVerify(() => grabImage(surface).equals(idle));
            robot.greet();
            tryVerify(() => !grabImage(surface).equals(idle));
        }
    }
}
