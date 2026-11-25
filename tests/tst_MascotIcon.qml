// SPDX-License-Identifier: MIT
// Draw transitions on the real component. A valid tray pose alone doesn't
// guarantee the separate floating SVG layers resolved and appeared.
import QtQuick
import QtTest
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui" as HappyBot

Item {
    width: 64
    height: 64
    HappyBot.IconActivity { id: cues }
    HappyBot.MascotIcon {
        id: face
        anchors.fill: parent
        activity: cues
        animate: false
    }
    TestCase {
        name: "Mascot"
        when: windowShown

        function capture() {
            waitForPolish(face);
            return grabImage(face);
        }

        function test_posesWithMotionDisabled() {
            const idle = capture();
            for (const entry of [["hot", "hot"], ["downloading", "download"],
                                 ["uploading", "upload"], ["recording", "recording"]]) {
                cues[entry[0]] = true;
                compare(cues.trayPose, entry[1]);
                tryVerify(() => !capture().equals(idle));
                cues[entry[0]] = false;
                tryVerify(() => capture().equals(idle));
            }
        }

        function test_recordingTakesPriorityAndRestoresActivity() {
            cues.apply({uploading: true, downloading: true});
            compare(cues.trayPose, "transfer");
            cues.hot = true;
            compare(cues.trayPose, "hot");
            cues.recording = true;
            compare(cues.trayPose, "recording");
            const recording = capture();
            cues.hot = false;
            cues.uploading = false;
            verify(capture().equals(recording));
            cues.recording = false;
            compare(cues.trayPose, "download");
            cues.apply({});
        }
    }
}
