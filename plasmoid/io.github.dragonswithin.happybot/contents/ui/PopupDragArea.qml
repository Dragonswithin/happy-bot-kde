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
    property point pressOrigin
    property bool dragging: false

    onPressed: mouse => {
        pressPosition = mapToItem(null, mouse.x, mouse.y);
        pressOrigin = popup.windowPosition();
        dragging = false;
    }
    onPositionChanged: mouse => {
        const point = mapToItem(null, mouse.x, mouse.y);
        const dx = point.x - pressPosition.x;
        const dy = point.y - pressPosition.y;
        if (!dragging && Math.abs(dx) + Math.abs(dy) < Qt.styleHints.startDragDistance)
            return;
        dragging = true;
        popup.previewWindowMove(Qt.point(pressOrigin.x + dx, pressOrigin.y + dy));
    }
    onReleased: mouse => {
        if (dragging) {
            const point = mapToItem(null, mouse.x, mouse.y);
            popup.windowMoved(Qt.point(pressOrigin.x + point.x - pressPosition.x,
                                       pressOrigin.y + point.y - pressPosition.y));
            popup.endWindowMove();
        }
        dragging = false;
    }
    onCanceled: {
        if (dragging)
            popup.endWindowMove();
        dragging = false;
    }
}
