// SPDX-License-Identifier: MIT
// Exercise the idle face and greeting on the real character at shortcut size.
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
            const pose = findChild(robot, "characterPose");
            verify(pose);
            return pose;
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
            const pose = enableMotion();
            const idle = grabImage(surface);
            const start = Date.now();
            robot.attentive = true;
            tryVerify(() => {
                const frame = grabImage(surface);
                return hasGold(frame, 0.25, 0, 0.70, 0.29)
                    && hasGold(frame, 0.71, 0.24, 0.99, 0.55);
            });
            const firstPose = grabImage(surface);
            tryVerify(() => pose.wrist > 10, robot.duration(4000));
            verify(Date.now() - start >= 1000, "The first full sweep should take time to read");
            const next = grabImage(surface);
            verify(!next.equals(firstPose) && !next.equals(idle));
            compare(robot.mapToItem(surface, 0, 0), Qt.point(0, 0));
            compare(robot.mapToItem(surface, robot.width, robot.height), Qt.point(32, 32));

            robot.animate = false;
            tryVerify(() => grabImage(surface).equals(grabImage(original)));
        }

        function test_idleLooksBothWaysAndReturnsToTheSameFace() {
            const pose = enableMotion();
            const idle = grabImage(surface);
            tryVerify(() => pose.gaze > 2, robot.duration(8000));
            const lookingRight = grabImage(surface);
            verify(!lookingRight.equals(idle));
            // The antenna, housing and smile must stay still when only the eyes move.
            for (let y = 0; y < idle.height; ++y) {
                if (y >= Math.floor(idle.height * 20 / 48) && y < Math.ceil(idle.height * 29 / 48)) continue;
                for (let x = 0; x < idle.width; ++x)
                    compare(lookingRight.pixel(x, y), idle.pixel(x, y));
            }
            const right = Date.now();
            tryVerify(() => pose.gaze < -2, robot.duration(4000));
            verify(Date.now() - right >= 650, "Allow time to look right and travel to the left");
            verify(!grabImage(surface).equals(lookingRight));
            tryVerify(() => pose.gaze === 0 && grabImage(surface).equals(idle), robot.duration(4000));
        }

        function test_hoverDuringGlanceKeepsEyePosition() {
            const pose = enableMotion();
            tryVerify(() => pose.gaze > 2, robot.duration(8000));
            const gaze = pose.gaze;
            robot.attentive = true;
            compare(pose.gaze, gaze);
            tryVerify(() => pose.gaze === 0 && pose.lift > 0, robot.duration(3000));
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
