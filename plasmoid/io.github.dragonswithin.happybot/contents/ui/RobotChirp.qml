// SPDX-License-Identifier: MIT
// Play the robot's two-note greeting through the user's current audio output.
import QtMultimedia

SoundEffect {
    id: chirp
    signal unavailable()
    property bool requested: false
    source: "../sounds/greeting.wav"
    volume: 0.32

    function greet() {
        if (status === SoundEffect.Ready) {
            play();
        } else if (status === SoundEffect.Error) {
            unavailable();
        } else {
            requested = true;
        }
    }
    onStatusChanged: {
        if (requested && (status === SoundEffect.Ready || status === SoundEffect.Error)) {
            requested = false;
            greet();
        }
    }
}
