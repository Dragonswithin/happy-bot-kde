/* SPDX-License-Identifier: MIT */
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: control
    required property var client
    required property string passage
    property string label: i18n("Read aloud")
    property string job: ""
    property string failure: ""
    property bool pending: false

    function failed(data) {
        pending = false
        job = ""
        failure = data.error || i18n("Could not read aloud.")
    }
    function stop() {
        if (job && client)
            client.request("POST", "/speech/stop", {job: job}, () => {}, failed)
    }

    onVisibleChanged: if (!visible) stop()
    Component.onDestruction: stop()
    QQC2.ToolButton {
        text: control.job ? i18n("Stop reading") : control.label
        icon.name: control.job ? "media-playback-stop" : "audio-speakers-symbolic"
        enabled: !!control.client && !control.pending
        onClicked: {
            if (control.job) {
                control.stop()
                return
            }
            control.pending = true
            control.failure = ""
            control.client.request("POST", "/speech/read", {text: control.passage}, data => {
                control.job = data.job
                control.pending = false
                if (!control.visible) control.stop()
                poll.restart()
            }, control.failed)
        }
    }
    Timer {
        id: poll
        interval: 250
        onTriggered: control.client.request("GET", "/speech/status?job=" + control.job, null, data => {
            if (data.playing) poll.restart()
            else {
                control.job = ""
                control.failure = data.error || ""
            }
        }, control.failed)
    }
    QQC2.Label {
        Layout.fillWidth: true
        visible: control.failure.length > 0
        text: control.failure
        wrapMode: Text.Wrap
        color: Kirigami.Theme.negativeTextColor
    }
}
