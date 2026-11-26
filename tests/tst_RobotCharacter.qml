// SPDX-License-Identifier: MIT
// Exercise idle eyes at shortcut size and the portrait and panel entry points.
import QtQuick
import QtTest
import org.kde.kirigami as Kirigami
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui" as HappyBot

Item {
    width: 232
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

    HappyBot.GreetingPortrait {
        id: portrait
        x: 120
        width: 48
        height: width
        animate: true
        visible: false
        iconSource: HappyBot.Look.robotIcon.toString()
    }

    HappyBot.IconActivity { id: activityState }
    HappyBot.PanelIcon {
        id: panelIcon
        x: 180
        width: 32
        height: width
        animateMascot: true
        visible: false
        activity: activityState
        iconName: HappyBot.Look.robotIcon.toString()
    }

    TestCase {
        name: "RobotCharacter"
        when: windowShown

        function init() {
            robot.animate = false;
            portrait.visible = false;
            panelIcon.visible = false;
            panelIcon.hovered = false;
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

        function test_motionOffRestoresTheOriginalIconDuringABlink() {
            const pose = enableMotion();
            tryVerify(() => pose.eyelid < 0.95, robot.duration(6000));
            robot.animate = false;
            tryCompare(pose, "eyelid", 1);
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

        function test_hidingAndShowingRestartsTheIdlePose() {
            const pose = enableMotion();
            const idle = grabImage(surface);
            tryVerify(() => pose.gaze > 2, robot.duration(8000));
            surface.visible = false;
            tryCompare(robot, "canMove", false);
            surface.visible = true;
            tryCompare(robot, "canMove", true);
            compare(pose.gaze, 0);
            compare(pose.eyelid, 1);
            tryVerify(() => grabImage(surface).equals(idle));
        }

        function test_showingPortraitAndHoveringPanelKeepTheRobotAtRest() {
            if (Kirigami.Units.longDuration <= 1) skip("Plasma animations are disabled");
            panelIcon.visible = true;
            portrait.visible = true;
            tryCompare(panelIcon, "status", Loader.Ready);
            waitForPolish(portrait);
            wait(50);
            const portraitAtRest = grabImage(portrait);
            const panelAtRest = grabImage(panelIcon);
            panelIcon.hovered = true;
            wait(700);  // Both entry points are still within the pause before the first idle blink.
            verify(grabImage(portrait).equals(portraitAtRest));
            verify(grabImage(panelIcon).equals(panelAtRest));
        }
    }
}
