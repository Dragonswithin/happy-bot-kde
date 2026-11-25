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
    readonly property string transfer: downloading && uploading ? "transfer"
        : downloading ? "download" : uploading ? "upload" : ""
    readonly property string expression: recording ? "recording" : hot ? "hot"
        : lowMemory ? "memory" : busy ? "busy" : ""
    readonly property string trayPose: expression || transfer

    function apply(snapshot) {
        busy = snapshot.busy === true;
        lowMemory = snapshot.low_memory === true;
        hot = snapshot.hot === true;
        downloading = snapshot.downloading === true;
        uploading = snapshot.uploading === true;
        recording = snapshot.recording === true;
    }
}
