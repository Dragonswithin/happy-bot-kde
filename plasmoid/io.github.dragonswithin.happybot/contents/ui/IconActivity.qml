// SPDX-License-Identifier: MIT
// Shared display priority for the floating mascot and its static tray pose.
import QtQuick

QtObject {
    property bool busy: false
    property bool lowMemory: false
    property bool hot: false
    property bool downloading: false
    property bool uploading: false
    property bool recording: false
    property bool nudgesEnabled: true
    property var nudges: []
    readonly property string transfer: downloading && uploading ? "transfer"
        : downloading ? "download" : uploading ? "upload" : ""
    readonly property string expression: recording ? "recording" : hot ? "hot"
        : lowMemory ? "memory" : busy ? "busy" : nudgesEnabled && nudges.length ? "nudge" : ""
    readonly property string trayPose: expression || transfer

    function description(): string {
        return recording ? i18n("Recording microphone") : trayPose === "nudge" ? Look.nudgeTitle(nudges[0]) : "";
    }

    function apply(snapshot) {
        busy = snapshot.busy === true;
        lowMemory = snapshot.low_memory === true;
        hot = snapshot.hot === true;
        downloading = snapshot.downloading === true;
        uploading = snapshot.uploading === true;
        recording = snapshot.recording === true;
        const known = ["battery", "disk", "restart", "updates"];
        const active = Array.isArray(snapshot.nudges)
            ? snapshot.nudges.filter((kind, index, all) => known.includes(kind) && all.indexOf(kind) === index)
            : [];
        // Ordinary activity updates should leave a focused nudge button in place.
        if (active.join() !== nudges.join()) {
            nudges = active;
        }
    }
}
