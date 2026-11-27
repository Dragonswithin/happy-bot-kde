// SPDX-License-Identifier: MIT
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

QQC2.ToolButton {
    id: meter
    required property var session
    required property color accent
    required property bool nativeLook
    readonly property var sample: session.contextUsage
    readonly property int capacity: Math.max(0, session.contextModel?.context_window ?? 0)
    readonly property int used: Math.max(0, sample?.used ?? 0)
    readonly property bool measured: !!sample && sample.model === session.contextModel?.name
    readonly property real fraction: measured && capacity > 0 ? used / capacity : 0
    readonly property bool nearLimit: measured && capacity > 0 && fraction >= 0.8
    readonly property string detail: {
        const source = sample?.estimated
            ? (sample.image_count ? i18n("Estimate excludes images") : i18n("Estimated"))
            : i18n("Provider reported for last request");
        if (capacity === 0)
            return measured ? i18n("%1 input tokens · Context capacity unavailable", count(used)) + " · " + source
                            : i18n("Context capacity unavailable");
        if (!measured)
            return i18n("Context capacity: %1 tokens", count(capacity));
        const amount = i18n("%1 of %2 context tokens", count(used), count(capacity));
        return (nearLimit ? i18n("Near context limit") + " · " : "") + amount + " · " + source;
    }

    function count(number) { return Number(number).toLocaleString(Qt.locale(), "f", 0); }

    focusPolicy: Qt.StrongFocus
    checkable: true
    Accessible.name: detail
    text: capacity === 0 ? i18n("Context —") : !measured ? i18n("Context")
        : (nearLimit ? "⚠ " : "") + (sample.estimated ? "≈" : "") + Math.round(fraction * 100) + "%"
    contentItem: ColumnLayout {
        spacing: Kirigami.Units.smallSpacing / 2

        QQC2.Label {
            Layout.fillWidth: true
            text: meter.text
            horizontalAlignment: Text.AlignHCenter
            Accessible.ignored: true
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 3
            radius: height / 2
            color: Qt.alpha(Kirigami.Theme.textColor, 0.18)

            Rectangle {
                width: parent.width * Math.min(1, meter.fraction)
                height: parent.height
                radius: parent.radius
                color: meter.nearLimit ? Kirigami.Theme.neutralTextColor : meter.accent
            }
        }
    }

    background: PopupControlBackground {
        nativeLook: meter.nativeLook
        accent: meter.accent
        highlighted: meter.hovered || meter.down
        emphasized: meter.visualFocus || meter.checked
    }

    AssistantToolTip {
        accent: meter.accent
        text: meter.detail
        visible: meter.hovered || meter.visualFocus || meter.checked
    }
}
