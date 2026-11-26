/*
    SPDX-License-Identifier: MIT
*/

import QtQuick
import org.kde.layershell as LayerShell

// The source window keeps the pointer grab in the same coordinate space until
// release. This input-transparent surface follows the pointer in its place.
PositionedWindow {
    id: preview
    property var snapshot: null
    readonly property bool ready: image.status === Image.Ready

    visible: ready && (Qt.platform.pluginName.startsWith("wayland") || Qt.platform.pluginName === "xcb")
    flags: Qt.FramelessWindowHint | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
    LayerShell.Window.scope: "happy-bot-move-preview"
    LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone

    Image {
        id: image
        anchors.fill: parent
        source: preview.snapshot?.url ?? ""
        cache: false
        smooth: false
    }
}
