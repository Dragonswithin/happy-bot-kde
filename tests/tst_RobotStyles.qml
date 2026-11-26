// SPDX-License-Identifier: MIT
// Each character has its own moving hardware above the common visor.
import QtQuick
import QtTest
import org.kde.kirigami as Kirigami
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui" as HappyBot

Item {
    id: scene
    readonly property var styles: ["pip", "rivet", "orbit", "watt", "pixel",
                                   "sprig", "nixie", "sprocket", "sonar", "dotty"]
    property bool moving: false
    property bool reference: true
    width: styles.length * 48
    height: 48

    // Qt Test samples the window in framebuffer pixels. Render each 48-pixel
    // icon in the same location at every desktop scale, including fractional.
    component Strip: Row {
        transformOrigin: Item.TopLeft
        scale: 1 / Screen.devicePixelRatio
    }

    Strip {
        id: robots
        visible: !scene.reference
        Repeater {
            id: characters
            model: scene.styles
            HappyBot.RobotCharacter {
                required property string modelData
                width: 48
                height: 48
                robotStyle: modelData
                animate: scene.moving
            }
        }
    }

    Strip {
        visible: scene.reference
        Repeater {
            id: assets
            model: scene.styles
            Image {
                required property string modelData
                width: 48
                height: 48
                sourceSize: Qt.size(width, height)
                source: "../plasmoid/io.github.dragonswithin.happybot/contents/images/"
                    + (modelData === "pip" ? "happy-bot.svg" : "robots/" + modelData + ".svg")
            }
        }
    }

    TestCase {
        name: "RobotStyles"
        when: windowShown

        function test_eachRobotMovesItsOwnHardwareAndReturnsToItsIcon() {
            for (let i = 0; i < assets.count; ++i)
                tryCompare(assets.itemAt(i), "status", Image.Ready);
            const staticIcons = grabImage(scene);
            scene.reference = false;
            tryVerify(() => grabImage(scene).equals(staticIcons));
            if (Kirigami.Units.longDuration <= 1) skip("Plasma animations are disabled");

            scene.moving = true;
            waitForRendering(robots);
            const resting = grabImage(scene);
            const first = characters.itemAt(0);
            const pose = findChild(first, "characterPose");
            verify(pose);
            tryVerify(() => pose.gesture > 0.55, first.duration(4500));
            const moving = grabImage(scene);
            const cellWidth = resting.width / characters.count;
            for (let i = 0; i < characters.count; ++i) {
                let changed = 0;
                // Above the visor, any changed pixels belong to the signature motion.
                for (let y = 0; y < Math.floor(resting.height * 18 / 48); ++y) {
                    for (let x = Math.floor(i * cellWidth); x < Math.floor((i + 1) * cellWidth); ++x) {
                        const difference = Math.abs(moving.red(x, y) - resting.red(x, y))
                            + Math.abs(moving.green(x, y) - resting.green(x, y))
                            + Math.abs(moving.blue(x, y) - resting.blue(x, y));
                        if (difference > 24) ++changed;
                    }
                }
                verify(changed >= 3, scene.styles[i] + " should visibly animate above the visor");
            }
            scene.moving = false;
            tryVerify(() => grabImage(scene).equals(staticIcons));
        }
    }
}
