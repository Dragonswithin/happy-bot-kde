/*
    SPDX-License-Identifier: MIT
*/

import QtQuick
import org.kde.plasma.components as PlasmaComponents3

PlasmaComponents3.ScrollView {
    id: scroll
    required property var popup

    // Put the drag area inside the viewport so controls and scrollbars receive
    // presses first, and ScrollView's own background cannot intercept them.
    property PopupDragArea dragArea: PopupDragArea {
        popup: scroll.popup
        parent: scroll.contentItem?.contentItem ?? null
        z: -1
        x: scroll.contentItem?.contentX ?? 0
        y: scroll.contentItem?.contentY ?? 0
        width: scroll.contentItem?.width ?? 0
        height: scroll.contentItem?.height ?? 0
    }
}
