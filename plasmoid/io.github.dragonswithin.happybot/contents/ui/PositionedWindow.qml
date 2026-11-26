/*
    SPDX-License-Identifier: MIT
*/

import QtQuick
import QtQuick.Window
import org.kde.layershell as LayerShell

Window {
    id: window

    readonly property int screenWidth: screen?.width ?? 1280
    readonly property int screenHeight: screen?.height ?? 720
    property point screenPosition
    property point popupPosition: Qt.point(-1, -1)
    signal popupMoved(int x, int y)

    color: "transparent"
    flags: Qt.FramelessWindowHint
    LayerShell.Window.layer: LayerShell.Window.LayerTop
    LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorLeft
    // Coordinates are relative to the screen, including the space reserved by panels.
    LayerShell.Window.exclusionZone: -1

    function movePopup(position, finished) {
        place(position.x, position.y);
        popupPosition = screenPosition;
        if (finished)
            popupMoved(popupPosition.x, popupPosition.y);
    }

    function place(left, top) {
        const next = Qt.point(
            Math.round(Math.max(0, Math.min(left, screenWidth - width))),
            Math.round(Math.max(0, Math.min(top, screenHeight - height))));
        if (Qt.platform.pluginName.startsWith("wayland")) {
            LayerShell.Window.margins = ({ left: next.x, top: next.y, right: 0, bottom: 0 });
        } else {
            x = contentItem.Screen.virtualX + next.x;
            y = contentItem.Screen.virtualY + next.y;
        }
        screenPosition = next;
        requestUpdate();
    }
}
