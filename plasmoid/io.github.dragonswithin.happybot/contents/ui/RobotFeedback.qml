// SPDX-License-Identifier: MIT
// Load the optional audio module only when the user asks for a greeting.
import QtQuick

Loader {
    id: feedback
    signal unavailable()
    active: false
    source: "RobotChirp.qml"

    function greet() {
        if (!active) {
            active = true;
        } else if (status === Loader.Error) {
            unavailable();
        } else if (item) {
            item.greet();
        }
    }
    onLoaded: item.greet()
    onStatusChanged: if (status === Loader.Error) unavailable()
    Connections {
        target: feedback.item
        function onUnavailable() { feedback.unavailable(); }
    }
}
