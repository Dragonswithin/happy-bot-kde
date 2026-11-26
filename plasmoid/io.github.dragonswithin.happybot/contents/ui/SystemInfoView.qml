/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

/**
 * System info: what the computer is doing, live, so System Monitor is rarely needed. ResultsView.qml
 * shows it while `session.showingSystem` is true (the start screen's optional "System info" button).
 *
 * The overview shows summary cards. Opening a card reveals its readings and charts.
 * Processor and Memory details also show the busiest programs and let users stop
 * their own programs after confirming.
 *
 * Data comes from the daemon (src/happy_bot/system_routes.py): `GET /system/overview` every
 * `overviewMs` while visible and `GET /system/programs` every `programsMs` in Processor or Memory details; the
 * graphs' history is kept by the daemon, so it is there as soon as the view opens. Sizes are shown
 * in powers of 1024 with GB/MB, speeds per second. The view keeps only the latest replies.
 */
ColumnLayout {
    id: view
    property color accent: Kirigami.Theme.highlightColor

    required property var session
    property var info: null
    property var programs: []
    property string detailSection: ""
    readonly property bool programsVisible: detailSection === "cpu" || detailSection === "memory"
    property string sort: "cpu"
    property int confirmPid: -1
    property string message: ""
    readonly property int overviewMs: 1000
    readonly property int programsMs: 2000

    spacing: Kirigami.Units.largeSpacing

    function openDetails(section) {
        if (section === "cpu" || section === "memory")
            view.sort = section;
        view.detailSection = section;
    }

    function back() {
        if (!view.detailSection)
            return false;
        view.detailSection = "";
        view.confirmPid = -1;
        view.message = "";
        view.programs = [];
        return true;
    }

    onVisibleChanged: if (!visible) back()

    function size(bytes) {
        if (bytes === null || bytes === undefined) {
            return "–";
        }
        const units = ["B", "KB", "MB", "GB", "TB"];
        let value = bytes, unit = 0;
        while (value >= 1024 && unit < units.length - 1) {
            value /= 1024;
            unit += 1;
        }
        return (value >= 100 || unit === 0 ? Math.round(value) : value.toFixed(1)) + " " + units[unit];
    }

    function rate(bytes) {
        return bytes === null || bytes === undefined ? "–" : i18n("%1/s", view.size(bytes));
    }

    function percent(value) {
        return value === null || value === undefined ? "–" : Math.round(value) + "%";
    }

    function degrees(value) {
        return value === null || value === undefined ? "" : Math.round(value) + " °C";
    }

    function uptime(seconds) {
        if (!seconds) {
            return "";
        }
        const days = Math.floor(seconds / 86400), hours = Math.floor(seconds % 86400 / 3600);
        return days > 0 ? i18np("%1 day", "%1 days", days) + ", " + i18np("%1 hour", "%1 hours", hours)
                        : i18np("%1 hour", "%1 hours", hours) + ", " + i18np("%1 minute", "%1 minutes", Math.floor(seconds % 3600 / 60));
    }

    function refresh() {
        view.session.request("GET", "/system/overview", null, data => view.info = data, data => {});
    }

    function refreshPrograms() {
        if (!view.programsVisible)
            return;
        const sort = view.sort;
        view.session.request("GET", "/system/programs?sort=" + sort, null, data => {
            if (view.programsVisible && view.sort === sort)
                view.programs = data.programs || [];
        }, () => {});
    }

    function stop(program) {
        view.confirmPid = -1;
        view.session.request("POST", "/system/stop", { pid: program.pid }, data => {
            view.message = data.message || "";
            view.refreshPrograms();
        }, data => view.message = data.error || i18n("It could not be stopped."));
    }

    Timer {
        interval: view.overviewMs
        repeat: true
        triggeredOnStart: true
        running: view.visible
        onTriggered: view.refresh()
    }

    Timer {
        interval: view.programsMs
        repeat: true
        triggeredOnStart: true
        running: view.visible && view.programsVisible
        onTriggered: view.refreshPrograms()
    }

    // A small line graph of the last minutes; `values` may hold nulls (no reading yet).
    component Sparkline: Canvas {
        id: spark
        property var values: []
        property real maximum: 100  // 0 = scale to the largest value
        property color stroke: view.accent
        Layout.fillWidth: true
        Layout.preferredHeight: Kirigami.Units.gridUnit * 1.6
        onValuesChanged: requestPaint()
        onStrokeChanged: requestPaint()
        onWidthChanged: requestPaint()
        onPaint: {
            const context = getContext("2d");
            context.reset();
            const points = (spark.values || []).filter(value => value !== null && value !== undefined);
            if (points.length < 2) {
                return;
            }
            const top = spark.maximum > 0 ? spark.maximum : Math.max(1, ...points);
            const step = width / (points.length - 1);
            context.beginPath();
            points.forEach((value, index) => {
                const y = height - Math.min(1, value / top) * (height - 2) - 1;
                if (index === 0) {
                    context.moveTo(0, y);
                } else {
                    context.lineTo(index * step, y);
                }
            });
            context.lineWidth = 1.5;
            context.strokeStyle = spark.stroke;
            context.stroke();
            context.lineTo(width, height);
            context.lineTo(0, height);
            context.closePath();
            context.fillStyle = Qt.alpha(spark.stroke, 0.15);
            context.fill();
        }
    }

    // One reading: a heading, its main value, a detail line, and optionally a graph or a bar.
    component Card: Rectangle {
        id: card
        required property string section
        property bool available: true
        objectName: "systemCard-" + section
        readonly property bool expanded: view.detailSection === section
        property string title: ""
        property string value: ""
        property string detail: ""
        property var graph: null
        property real graphMaximum: 100
        property real bar: -1  // 0..1 to draw a bar
        Layout.fillWidth: true
        Layout.preferredWidth: 1
        implicitHeight: column.implicitHeight + Kirigami.Units.largeSpacing * 2
        radius: Kirigami.Units.cornerRadius * 2
        visible: available && (!view.detailSection || expanded)
        color: Qt.alpha(hover.hovered && !expanded ? view.accent : Kirigami.Theme.textColor,
                        hover.hovered && !expanded ? 0.14 : 0.04)
        border.color: activeFocus ? view.accent : Qt.alpha(Kirigami.Theme.textColor, 0.12)
        activeFocusOnTab: !expanded
        Accessible.role: expanded ? Accessible.Grouping : Accessible.Button
        Accessible.name: card.title
        Accessible.description: card.value
        Accessible.onPressAction: if (!expanded) view.openDetails(section)
        Keys.onReturnPressed: if (!expanded) view.openDetails(section)
        Keys.onEnterPressed: if (!expanded) view.openDetails(section)
        Keys.onSpacePressed: if (!expanded) view.openDetails(section)
        HoverHandler { id: hover; cursorShape: card.expanded ? Qt.ArrowCursor : Qt.PointingHandCursor }
        TapHandler { enabled: !card.expanded; onTapped: view.openDetails(card.section) }

        ColumnLayout {
            id: column
            anchors.fill: parent
            anchors.margins: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.smallSpacing

            RowLayout {
                Layout.fillWidth: true
                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    text: card.title
                    font: Kirigami.Theme.smallFont
                    opacity: 0.75
                }
                Kirigami.Icon {
                    visible: !card.expanded
                    source: "go-next"
                    Layout.preferredWidth: Kirigami.Units.iconSizes.small
                    Layout.preferredHeight: Layout.preferredWidth
                    Accessible.ignored: true
                }
            }
            PlasmaComponents3.Label {
                Layout.fillWidth: true
                text: card.value
                font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.3
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            PlasmaComponents3.Label {
                Layout.fillWidth: true
                visible: card.expanded && card.detail.length > 0
                text: card.detail
                font: Kirigami.Theme.smallFont
                opacity: 0.75
                wrapMode: Text.Wrap
            }
            QQC2.ProgressBar {
                Layout.fillWidth: true
                visible: card.expanded && card.bar >= 0
                from: 0
                to: 1
                value: Math.max(0, card.bar)
            }
            Sparkline {
                visible: card.expanded && card.graph !== null
                values: card.graph || []
                maximum: card.graphMaximum
            }
        }
    }

    PlasmaComponents3.Label {
        visible: view.info === null
        text: i18n("Reading the system…")
        opacity: 0.7
    }

    GridLayout {
        Layout.fillWidth: true
        visible: view.info !== null
        columns: !view.detailSection && view.width >= Kirigami.Units.gridUnit * 24 ? 2 : 1
        columnSpacing: Kirigami.Units.smallSpacing
        rowSpacing: Kirigami.Units.smallSpacing

        Card {
            section: "cpu"
            title: i18n("Processor")
            value: view.info ? view.percent(view.info.cpu.percent) : ""
            detail: view.info ? [view.info.cpu.model || "", view.degrees(view.info.cpu.temp_c),
                                 i18np("%1 core", "%1 cores", view.info.cpu.cores),
                                 view.info.cpu.load.length ? i18n("load %1", view.info.cpu.load.map(v => v.toFixed(1)).join(" ")) : ""]
                                .filter(part => part.length > 0).join(" · ") : ""
            graph: view.info ? view.info.history.cpu : null
        }

        Card {
            section: "memory"
            title: i18n("Memory")
            value: view.info ? i18n("%1 of %2", view.size(view.info.memory.used), view.size(view.info.memory.total)) : ""
            detail: view.info && view.info.memory.swap_total > 0
                ? i18n("Swap: %1 of %2", view.size(view.info.memory.swap_used), view.size(view.info.memory.swap_total)) : ""
            graph: view.info ? view.info.history.memory : null
        }

        Repeater {
            model: view.info ? view.info.gpus : []

            Card {
                required property var modelData
                required property int index
                section: "gpu-" + index
                title: view.info.gpus.length > 1 ? i18n("Graphics %1", index + 1) : i18n("Graphics")
                value: view.percent(modelData.busy_percent)
                detail: [modelData.name, view.degrees(modelData.temp_c),
                         modelData.memory_total ? i18n("memory %1 of %2", view.size(modelData.memory_used), view.size(modelData.memory_total)) : "",
                         modelData.shared_total ? i18n("shared %1 of %2", view.size(modelData.shared_used), view.size(modelData.shared_total)) : ""]
                        .filter(part => part.length > 0).join(" · ")
            }
        }

        Card {
            section: "network"
            title: view.info && view.info.network.interface ? i18n("Network (%1)", view.info.network.interface) : i18n("Network")
            value: view.info ? "↓ " + view.rate(view.info.network.receive_bps) : ""
            detail: view.info ? "↑ " + view.rate(view.info.network.send_bps) : ""
            graph: view.info ? view.info.history.receive : null
            graphMaximum: 0
        }

        Card {
            section: "battery"
            available: !!(view.info && view.info.battery)
            title: i18n("Battery")
            value: view.info && view.info.battery ? view.info.battery.percent + "%" : ""
            detail: view.info && view.info.battery
                ? [view.info.battery.status, view.info.battery.hours_left ? i18n("%1 h left", view.info.battery.hours_left) : ""]
                  .filter(part => part.length > 0).join(" · ") : ""
            bar: view.info && view.info.battery ? view.info.battery.percent / 100 : -1
        }
        Card {
            section: "storage"
            title: i18n("Storage")
            value: view.info ? i18np("%1 disk", "%1 disks", view.info.disks.length) : ""
        }

        Card {
            section: "uptime"
            available: !!view.info?.uptime_seconds
            title: i18n("Uptime")
            value: view.info ? view.uptime(view.info.uptime_seconds) : ""
            detail: view.info?.uptime_seconds
                ? i18n("Started %1", new Date(Date.now() - view.info.uptime_seconds * 1000).toLocaleString(Qt.locale(), Locale.ShortFormat)) : ""
        }
    }

    Kirigami.Heading {
        visible: view.detailSection === "storage"
        level: 5
        text: i18n("Disks")
        opacity: 0.7
    }

    Repeater {
        model: view.detailSection === "storage" ? view.info.disks : []

        ColumnLayout {
            required property var modelData
            Layout.fillWidth: true
            spacing: 2

            RowLayout {
                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    text: modelData.mount
                    elide: Text.ElideMiddle
                }
                PlasmaComponents3.Label {
                    text: i18n("%1 free of %2", view.size(modelData.total - modelData.used), view.size(modelData.total))
                    font: Kirigami.Theme.smallFont
                    opacity: 0.75
                }
            }
            QQC2.ProgressBar {
                Layout.fillWidth: true
                from: 0
                to: Math.max(1, modelData.total)
                value: modelData.used
            }
        }
    }

    RowLayout {
        visible: view.programsVisible
        Layout.fillWidth: true
        Layout.topMargin: Kirigami.Units.largeSpacing

        Kirigami.Heading {
            Layout.fillWidth: true
            level: 5
            text: i18n("Programs")
            opacity: 0.7
        }

        Repeater {
            model: [{ sort: "cpu", label: i18n("CPU") }, { sort: "memory", label: i18n("Memory") }]

            PlasmaComponents3.ToolButton {
                required property var modelData
                text: modelData.label
                checkable: true
                checked: view.sort === modelData.sort
                onClicked: {
                    view.sort = modelData.sort;
                    checked = Qt.binding(() => view.sort === modelData.sort);
                    view.refreshPrograms();
                }
            }
        }
    }

    Kirigami.InlineMessage {
        Layout.fillWidth: true
        visible: view.programsVisible && view.message.length > 0
        text: view.message
        showCloseButton: true
        onVisibleChanged: if (!visible) view.message = ""
    }

    Repeater {
        model: view.programsVisible ? view.programs : []

        ColumnLayout {
            id: program
            required property var modelData
            Layout.fillWidth: true
            spacing: 0

            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    text: program.modelData.mine ? program.modelData.name
                        : i18n("%1 (%2)", program.modelData.name, program.modelData.user)
                    elide: Text.ElideRight
                    opacity: program.modelData.mine ? 1 : 0.7
                }
                PlasmaComponents3.Label {
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 3
                    horizontalAlignment: Text.AlignRight
                    text: program.modelData.cpu_percent.toFixed(1) + "%"
                    font: Kirigami.Theme.smallFont
                }
                PlasmaComponents3.Label {
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 4
                    horizontalAlignment: Text.AlignRight
                    text: view.size(program.modelData.memory)
                    font: Kirigami.Theme.smallFont
                }
                PlasmaComponents3.ToolButton {
                    icon.name: "process-stop"
                    enabled: program.modelData.mine && !program.modelData.protected
                    opacity: enabled ? 1 : 0
                    AssistantToolTip {
                        accent: view.accent
                        text: i18n("Stop %1", program.modelData.name)
                        visible: parent.hovered
                    }
                    Accessible.name: i18n("Stop %1", program.modelData.name)
                    onClicked: view.confirmPid = program.modelData.pid
                }
            }

            RowLayout {
                visible: view.confirmPid === program.modelData.pid
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    text: i18n("Stop %1? Unsaved work in it is lost.", program.modelData.name)
                }
                PlasmaComponents3.Button {
                    text: i18n("Stop")
                    icon.name: "process-stop"
                    onClicked: view.stop(program.modelData)
                }
                PlasmaComponents3.Button {
                    text: i18n("Cancel")
                    onClicked: view.confirmPid = -1
                }
            }
        }
    }
}
