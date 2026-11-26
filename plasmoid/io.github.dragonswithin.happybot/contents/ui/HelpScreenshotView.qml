// SPDX-License-Identifier: MIT
pragma ComponentBehavior: Bound

import QtQuick
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PC3

Rectangle {
    id: viewport

    required property url source
    required property string action
    required property bool busy
    signal editRequested(string action, var coordinates)

    readonly property alias imageStatus: picture.status
    property real zoom: 1
    readonly property real maximumZoom: Math.max(16, 1 / Math.max(0.001, fitScale))
    // Keep the last decoded size while an edit replaces the image asynchronously.
    property size imageSize: Qt.size(0, 0)
    readonly property real fitScale: imageSize.width > 0 && imageSize.height > 0
        ? Math.min(width / imageSize.width, height / imageSize.height) : 0
    property point center: Qt.point(0.5, 0.5)
    clip: true
    color: Qt.alpha(Kirigami.Theme.textColor, 0.045)

    function fit() {
        zoom = 1;
        center = Qt.point(0.5, 0.5);
    }

    function offset(viewSize, imageSize, fraction) {
        return imageSize <= viewSize ? (viewSize - imageSize) / 2
            : Math.max(viewSize - imageSize, Math.min(0, viewSize / 2 - imageSize * fraction));
    }

    function imagePoint(x, y) {
        if (picture.width <= 0 || picture.height <= 0) return Qt.point(0, 0);
        return Qt.point(Math.max(0, Math.min(1, (x - picture.x) / picture.width)),
                        Math.max(0, Math.min(1, (y - picture.y) / picture.height)));
    }

    function zoomAt(factor, x, y) {
        if (picture.status !== Image.Ready || mouse.pressed) return;
        const next = Math.max(1, Math.min(maximumZoom, zoom * factor));
        if (next === zoom) return;
        if (next === 1) { fit(); return; }
        const pixel = imagePoint(x, y);
        zoom = next;
        center = Qt.point(pixel.x + (width / 2 - x) / picture.width,
                          pixel.y + (height / 2 - y) / picture.height);
    }

    Image {
        id: picture
        source: viewport.source
        // Decode at the capture's native resolution so zoom reveals the original pixels.
        asynchronous: true
        cache: false
        mipmap: true
        width: viewport.imageSize.width * viewport.fitScale * viewport.zoom
        height: viewport.imageSize.height * viewport.fitScale * viewport.zoom
        x: viewport.offset(viewport.width, width, viewport.center.x)
        y: viewport.offset(viewport.height, height, viewport.center.y)
        fillMode: Image.PreserveAspectFit
        Accessible.role: Accessible.Graphic
        Accessible.name: i18n("Screenshot preview")
        Component.onCompleted: {
            // Qt 6.8 added the option to keep the previous image painted during a reload.
            if ("retainWhileLoading" in picture) picture.retainWhileLoading = true;
        }
        onStatusChanged: {
            if (status === Image.Null) {
                viewport.imageSize = Qt.size(0, 0);
                viewport.fit();
            } else if (status === Image.Ready && (sourceSize.width !== viewport.imageSize.width
                       || sourceSize.height !== viewport.imageSize.height)) {
                viewport.imageSize = Qt.size(sourceSize.width, sourceSize.height);
                viewport.fit();
            }
        }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.MiddleButton
        enabled: picture.status === Image.Ready && !viewport.busy
        preventStealing: true
        readonly property bool selecting: viewport.action === "point" || viewport.action === "crop"
        cursorShape: panning ? Qt.ClosedHandCursor : selecting ? Qt.CrossCursor
            : viewport.zoom > 1 ? Qt.OpenHandCursor : Qt.ArrowCursor
        property bool panning: false
        property point start
        property point startPixel
        property point end
        property point origin

        onWheel: wheel => {
            const steps = wheel.pixelDelta.y ? wheel.pixelDelta.y / 80 : wheel.angleDelta.y / 120;
            if (steps) viewport.zoomAt(Math.pow(1.3, steps), wheel.x, wheel.y);
            wheel.accepted = true;
        }
        onPressed: event => {
            panning = event.button === Qt.MiddleButton || !selecting;
            start = Qt.point(event.x, event.y);
            end = start;
            startPixel = viewport.imagePoint(event.x, event.y);
            origin = Qt.point(picture.x, picture.y);
            if (!panning && !picture.contains(picture.mapFromItem(mouse, start))) event.accepted = false;
        }
        onPositionChanged: event => {
            if (!pressed) return;
            end = Qt.point(event.x, event.y);
            if (panning && viewport.zoom > 1) {
                viewport.center = Qt.point((width / 2 - origin.x - end.x + start.x) / picture.width,
                                           (height / 2 - origin.y - end.y + start.y) / picture.height);
            }
        }
        onCanceled: panning = false
        onReleased: event => {
            if (panning) { panning = false; return; }
            const a = startPixel;
            const b = viewport.imagePoint(event.x, event.y);
            if (viewport.action === "point") viewport.editRequested("point", [b.x, b.y]);
            else if (viewport.action === "crop" && Math.abs(a.x - b.x) * picture.width >= 3
                     && Math.abs(a.y - b.y) * picture.height >= 3)
                viewport.editRequested("crop", [Math.min(a.x, b.x), Math.min(a.y, b.y), Math.max(a.x, b.x), Math.max(a.y, b.y)]);
        }

        Rectangle {
            visible: mouse.pressed && !mouse.panning && viewport.action === "crop"
            readonly property point boundedEnd: viewport.imagePoint(mouse.end.x, mouse.end.y)
            readonly property real rightEdge: picture.x + boundedEnd.x * picture.width
            readonly property real bottomEdge: picture.y + boundedEnd.y * picture.height
            x: Math.min(mouse.start.x, rightEdge)
            y: Math.min(mouse.start.y, bottomEdge)
            width: Math.abs(rightEdge - mouse.start.x)
            height: Math.abs(bottomEdge - mouse.start.y)
            border.color: "white"
            border.width: 2
            color: Qt.alpha(Kirigami.Theme.highlightColor, 0.25)
        }
    }

    PC3.BusyIndicator {
        anchors.centerIn: parent
        running: viewport.busy || picture.status === Image.Loading
        visible: running
    }
}
