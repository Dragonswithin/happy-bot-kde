// SPDX-License-Identifier: MIT
// Shared display priority for the floating mascot and its static tray pose.
import QtQuick

QtObject {
    property bool hot: false
    property bool downloading: false
    property bool uploading: false
    property bool recording: false
    readonly property string transfer: downloading && uploading ? "transfer"
        : downloading ? "download" : uploading ? "upload" : ""
    readonly property string trayPose: recording ? "recording" : hot ? "hot" : transfer

    function apply(snapshot) {
        hot = snapshot.hot === true;
        downloading = snapshot.downloading === true;
        uploading = snapshot.uploading === true;
        recording = snapshot.recording === true;
    }
}
