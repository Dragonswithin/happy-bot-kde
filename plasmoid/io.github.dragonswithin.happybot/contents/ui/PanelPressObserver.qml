/*
    SPDX-License-Identifier: MIT
*/

import QtQuick

Item {
    id: observer

    property Item applet
    signal outsidePressed()

    anchors.fill: parent
    z: 1000

    PointHandler {
        // PointHandler observes a passive grab while the panel handles the click.
        acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
        onActiveChanged: {
            const applet = observer.applet;
            if (active && applet && !applet.contains(applet.mapFromItem(observer, point.position)))
                observer.outsidePressed();
        }
    }
}
