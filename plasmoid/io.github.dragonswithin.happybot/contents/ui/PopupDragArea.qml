/*
    SPDX-License-Identifier: MIT
*/

import QtQuick

MouseArea {
    required property var popup

    enabled: popup?.windowPosition != null
    cursorShape: dragging ? Qt.ClosedHandCursor : Qt.ArrowCursor
    preventStealing: true
    scrollGestureEnabled: false

    property point pressPosition
    property bool dragging: false

    onPressed: mouse => {
        pressPosition = mapToItem(null, mouse.x, mouse.y);
        dragging = false;
    }
    onPositionChanged: mouse => {
        const point = mapToItem(null, mouse.x, mouse.y);
        const dx = point.x - pressPosition.x;
        const dy = point.y - pressPosition.y;
        if (!dragging && Math.abs(dx) + Math.abs(dy) < Qt.styleHints.startDragDistance)
            return;
        dragging = true;
        const origin = popup.windowPosition();
        popup.windowMoved(Qt.point(origin.x + dx, origin.y + dy), false);
    }
    onReleased: {
        if (dragging)
            popup.windowMoved(popup.windowPosition(), true);
        dragging = false;
    }
    onCanceled: dragging = false
}
