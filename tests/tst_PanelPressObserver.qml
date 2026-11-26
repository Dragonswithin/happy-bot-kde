// SPDX-License-Identifier: MIT
import QtQuick
import QtTest
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui" as HappyBot

Item {
    width: 400
    height: 40

    Item {
        id: botApplet
        width: 50
        height: parent.height
    }

    MouseArea {
        id: taskbar
        x: botApplet.width
        width: parent.width - x
        height: parent.height
    }

    HappyBot.PanelPressObserver {
        id: observer
        applet: botApplet
    }

    SignalSpy { id: outside; target: observer; signalName: "outsidePressed" }
    SignalSpy { id: clicked; target: taskbar; signalName: "clicked" }

    TestCase {
        name: "PanelPressObserver"
        when: windowShown

        function test_passiveOutsidePress() {
            mouseClick(botApplet, 15, 15);
            compare(outside.count, 0);
            mousePress(taskbar, 15, 15);
            compare(outside.count, 1);
            mouseRelease(taskbar, 15, 15);
            compare(clicked.count, 1);
        }
    }
}
