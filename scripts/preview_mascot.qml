// SPDX-License-Identifier: MIT
// Run with qml6 scripts/preview_mascot.qml. No daemon or microphone access.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../plasmoid/io.github.dragonswithin.happybot/contents/ui" as HappyBot

ApplicationWindow {
    id: preview
    title: "Happy Bot icon preview"
    width: 450
    height: 310
    visible: true

    HappyBot.IconActivity {
        id: demo
        lowMemory: memory.checked
        busy: cpu.checked
        hot: heat.checked
        downloading: down.checked
        uploading: up.checked
        recording: mic.checked
        nudges: note.checked ? ["battery"] : []
    }
    HappyBot.IconActivity {
        id: tray
        lowMemory: demo.trayPose === "memory"
        busy: demo.trayPose === "busy"
        hot: demo.trayPose === "hot"
        downloading: demo.trayPose === "download" || demo.trayPose === "transfer"
        uploading: demo.trayPose === "upload" || demo.trayPose === "transfer"
        recording: demo.recording
        nudges: demo.trayPose === "nudge" ? demo.nudges : []
    }

    ColumnLayout {
        anchors.centerIn: parent
        spacing: 12
        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: 36
            ColumnLayout {
                HappyBot.MascotIcon {
                    Layout.alignment: Qt.AlignHCenter
                    Layout.preferredWidth: 80
                    Layout.preferredHeight: 80
                    activity: demo
                    animate: motion.checked
                }
                Label { text: "Floating · enlarged" }
            }
            ColumnLayout {
                HappyBot.MascotIcon {
                    Layout.alignment: Qt.AlignHCenter
                    Layout.preferredWidth: 32
                    Layout.preferredHeight: 32
                    activity: demo
                    animate: motion.checked
                }
                Label { text: "32 px" }
            }
            ColumnLayout {
                HappyBot.MascotIcon {
                    Layout.alignment: Qt.AlignHCenter
                    Layout.preferredWidth: 22
                    Layout.preferredHeight: 22
                    activity: tray
                    animate: false
                }
                Label { text: "Tray · 22 px" }
            }
        }
        GridLayout {
            columns: 2
            CheckBox { id: mic; text: "Recording microphone"; checked: true }
            CheckBox { id: heat; text: "CPU hot" }
            CheckBox { id: cpu; text: "CPU busy" }
            CheckBox { id: memory; text: "Low memory" }
            CheckBox { id: down; text: "Downloading" }
            CheckBox { id: up; text: "Uploading" }
            CheckBox { id: note; text: "Mascot nudge" }
            CheckBox { id: motion; text: "Animate"; checked: true }
        }
    }
}
