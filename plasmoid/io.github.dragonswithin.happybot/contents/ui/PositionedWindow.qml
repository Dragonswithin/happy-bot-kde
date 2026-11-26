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
    property point resizeOrigin
    property int resizeOriginHeight: 0
    property bool popupGrowsUp: false
    signal popupMoved(int x, int y)

    color: "transparent"
    flags: Qt.FramelessWindowHint
    LayerShell.Window.layer: LayerShell.Window.LayerTop
    LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorLeft
    // Coordinates are relative to the screen, including the space reserved by panels.
    LayerShell.Window.exclusionZone: -1

    function movePopup(position) {
        place(position.x, position.y);
        popupPosition = screenPosition;
        anchorPopup(screenPosition.x, screenPosition.y, height);
        popupMoved(popupPosition.x, popupPosition.y);
    }

    // Keep the original edge across the whole resize, including animated frames.
    function anchorPopup(left, top, openingHeight) {
        resizeOrigin = Qt.point(left, Math.max(0, Math.min(top, screenHeight - openingHeight)));
        resizeOriginHeight = openingHeight;
    }

    function placeResizedPopup(targetHeight, horizontalOffset = 0) {
        const bottom = resizeOrigin.y + resizeOriginHeight;
        popupGrowsUp = targetHeight <= bottom;
        place(resizeOrigin.x + horizontalOffset, popupGrowsUp ? bottom - height : resizeOrigin.y);
    }

    function place(left, top) {
        const next = Qt.point(
            Math.round(Math.max(0, Math.min(left, screenWidth - width))),
            Math.round(Math.max(0, Math.min(top, screenHeight - height))));
        LayerShell.Window.margins = ({ left: next.x, top: next.y, right: 0, bottom: 0 });
        // On Wayland, the compositor positions this surface using the margins.
        if (Qt.platform.pluginName === "xcb") {
            x = contentItem.Screen.virtualX + next.x;
            y = contentItem.Screen.virtualY + next.y;
        }
        screenPosition = next;
        requestUpdate();
    }
}
