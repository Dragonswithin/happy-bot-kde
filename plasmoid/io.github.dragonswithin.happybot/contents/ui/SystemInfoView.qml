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
 * Processor and Memory details show a sortable list of programs and let users stop
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
    signal revealCardRequested(Item card)
    property string detailSection: ""
    readonly property bool overviewDetail: ["hardware", "os", "uptime"].includes(detailSection)
    readonly property bool programsVisible: detailSection === "cpu" || detailSection === "memory"
    property string sort: "cpu"
    property bool sortDescending: true
    property int programRequest: 0
    readonly property real userColumnWidth: Kirigami.Units.gridUnit * 4
    readonly property real cpuColumnWidth: Kirigami.Units.gridUnit * 3
    readonly property real memoryColumnWidth: Kirigami.Units.gridUnit * 4
    property int confirmPid: -1
    property string message: ""
    readonly property int overviewMs: 1000
    readonly property int programsMs: 2000

    spacing: Kirigami.Units.largeSpacing

    function openDetails(section) {
        if (section === "cpu" || section === "memory") {
            view.sort = section;
            view.sortDescending = true;
        }
        view.forceActiveFocus();
        view.detailSection = section;
    }

    function back() {
        if (!view.detailSection)
            return false;
        view.detailSection = "";
        view.confirmPid = -1;
        view.message = "";
        view.programRequest++;
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
        const request = ++view.programRequest;
        const order = view.sortDescending ? "desc" : "asc";
        view.session.request("GET", "/system/programs?sort=" + view.sort + "&order=" + order, null, data => {
            if (view.programsVisible && view.programRequest === request)
                view.programs = data.programs || [];
        }, () => {});
    }

    function sortPrograms(column) {
        view.sortDescending = view.sort === column ? !view.sortDescending : column !== "user";
        view.sort = column;
        view.refreshPrograms();
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
        property string overviewIcon: ""
        property string overviewIconFallback: "preferences-system"
        readonly property bool iconSummary: overviewIcon.length > 0 && !expanded
        property string value: ""
        property string detail: ""
        property var graph: null
        property real graphMaximum: 100
        property Component detailContent
        property real uptimeFraction: -1
        property real bar: -1  // 0..1 to draw a bar
        Layout.fillWidth: true
        Layout.preferredWidth: 1
        Layout.preferredHeight: expanded ? implicitHeight : Math.max(width, implicitHeight)
        implicitHeight: (iconSummary ? iconColumn.implicitHeight : column.implicitHeight)
            + Kirigami.Units.largeSpacing * 2
        radius: Kirigami.Units.cornerRadius * 2
        visible: available && (!view.detailSection || expanded)
        color: Qt.alpha(hover.hovered && !expanded ? view.accent : Kirigami.Theme.textColor,
                        hover.hovered && !expanded ? 0.14 : 0.04)
        border.color: activeFocus ? view.accent : Qt.alpha(Kirigami.Theme.textColor, 0.12)
        activeFocusOnTab: !expanded
        onActiveFocusChanged: if (activeFocus && !expanded) view.revealCardRequested(card)
        Accessible.role: expanded ? Accessible.Grouping : Accessible.Button
        Accessible.name: card.title
        Accessible.description: card.iconSummary ? "" : card.value
        Accessible.onPressAction: if (!expanded) view.openDetails(section)
        Keys.onReturnPressed: if (!expanded) view.openDetails(section)
        Keys.onEnterPressed: if (!expanded) view.openDetails(section)
        Keys.onSpacePressed: if (!expanded) view.openDetails(section)
        HoverHandler { id: hover; cursorShape: card.expanded ? Qt.ArrowCursor : Qt.PointingHandCursor }
        TapHandler { enabled: !card.expanded; onTapped: view.openDetails(card.section) }

        ColumnLayout {
            id: iconColumn
            anchors.centerIn: parent
            width: Math.max(0, parent.width - Kirigami.Units.smallSpacing * 2)
            visible: card.iconSummary
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Icon {
                objectName: "systemIcon-" + card.section
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: Math.min(iconColumn.width, Kirigami.Units.iconSizes.huge)
                Layout.preferredHeight: Layout.preferredWidth
                source: card.overviewIcon
                fallback: card.overviewIconFallback
                Accessible.ignored: true
            }

            PlasmaComponents3.Label {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                text: card.title
                font: Kirigami.Theme.smallFont
                wrapMode: Text.Wrap
                Accessible.ignored: true
            }
        }

        ColumnLayout {
            id: column
            visible: !card.iconSummary
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
                elide: card.expanded ? Text.ElideNone : Text.ElideRight
                wrapMode: card.expanded ? Text.Wrap : Text.NoWrap
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
                objectName: "systemGraph-" + card.section
                visible: card.graph !== null
                values: card.graph || []
                maximum: card.graphMaximum
            }
            Loader {
                Layout.fillWidth: true
                active: card.expanded && card.detailContent !== null
                visible: active
                sourceComponent: card.detailContent
            }
            ColumnLayout {
                visible: card.uptimeFraction >= 0
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing
                Accessible.name: i18n("Time online in the last 24 hours")
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: Kirigami.Units.smallSpacing * 2
                    radius: height / 2
                    color: Qt.alpha(Kirigami.Theme.textColor, 0.12)
                    Rectangle {
                        anchors.right: parent.right
                        width: Math.max(0, card.uptimeFraction) * parent.width
                        height: parent.height
                        radius: parent.radius
                        color: view.accent
                    }
                }
                PlasmaComponents3.Label {
                    text: i18n("Last 24 hours")
                    font: Kirigami.Theme.smallFont
                    opacity: 0.75
                }
            }

        }
    }

    PlasmaComponents3.Label {
        visible: view.info === null
        text: i18n("Reading the system…")
        opacity: 0.7
    }

    component CardGrid: GridLayout {
        Layout.fillWidth: true
        columns: view.detailSection ? 1 : Math.max(1, Math.min(4,
            Math.floor((width + columnSpacing) / (Kirigami.Units.gridUnit * 6.5 + columnSpacing))))
        uniformCellWidths: true
        columnSpacing: Kirigami.Units.smallSpacing
        rowSpacing: Kirigami.Units.smallSpacing
    }

    Kirigami.Heading {
        visible: view.info !== null && !view.detailSection
        level: 4
        text: i18n("Live activity")
    }

    CardGrid {
        visible: view.info !== null && !view.overviewDetail

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
            value: view.info ? (expanded
                ? i18n("%1 of %2 system RAM used", view.size(view.info.memory.used), view.size(view.info.memory.total))
                : i18n("%1 of %2", view.size(view.info.memory.used), view.size(view.info.memory.total))) : ""
            detail: view.info ? [
                i18n("System RAM available: %1", view.size(view.info.memory.total - view.info.memory.used)),
                view.info.memory.swap_total > 0
                    ? i18n("Swap: %1 of %2", view.size(view.info.memory.swap_used), view.size(view.info.memory.swap_total)) : ""
            ].filter(Boolean).join("\n") : ""
            bar: view.info?.memory?.total > 0 ? view.info.memory.used / view.info.memory.total : -1
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
                graph: view.info?.history?.gpu?.[modelData.id] ?? null
                detail: [modelData.name, view.degrees(modelData.temp_c),
                         modelData.memory_total ? i18n("memory %1 of %2", view.size(modelData.memory_used), view.size(modelData.memory_total)) : "",
                         modelData.shared_total ? i18n("shared %1 of %2", view.size(modelData.shared_used), view.size(modelData.shared_total)) : ""]
                        .filter(part => part.length > 0).join(" · ")
            }
        }

        Card {
            section: "network"
            title: view.info && view.info.network.interface ? i18n("Network (%1)", view.info.network.interface) : i18n("Network")
            value: view.info ? (expanded
                ? i18n("Download: %1", view.rate(view.info.network.receive_bps))
                : "↓ " + view.rate(view.info.network.receive_bps)) : ""
            graph: view.info ? view.info.history.receive : null
            graphMaximum: 0
            detailContent: ColumnLayout {
                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    text: i18n("Upload: %1", view.rate(view.info?.network?.send_bps))
                    font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.3
                    font.weight: Font.DemiBold
                    wrapMode: Text.Wrap
                }

                Sparkline {
                    objectName: "systemGraph-network-upload"
                    values: view.info?.history?.send ?? []
                    maximum: 0
                }
            }
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
            section: "disk-activity"
            title: i18n("Disk activity")
            value: view.rate(graph?.length ? graph[graph.length - 1] : null)
            graph: view.info?.history?.disk ?? null
            graphMaximum: 0
            detail: i18n("Read and write throughput")
        }

        Card {
            section: "temperatures"
            title: i18n("Temperatures")
            available: view.info?.cpu?.temp_c != null || !!view.info?.gpus?.some(gpu => gpu.temp_c != null)
            value: view.degrees(view.info?.cpu?.temp_c)
                || view.degrees(view.info?.gpus?.find(gpu => gpu.temp_c != null)?.temp_c)
            detail: view.info ? [view.info.cpu.temp_c != null ? i18n("Processor: %1", view.degrees(view.info.cpu.temp_c)) : "",
                                 ...view.info.gpus.filter(gpu => gpu.temp_c != null)
                                      .map(gpu => i18n("%1: %2", gpu.name, view.degrees(gpu.temp_c)))]
                               .filter(label => label.length > 0).join("\n") : ""
            graph: view.info?.cpu?.temp_c != null ? view.info.history.temp ?? null : null
        }
    }

    Kirigami.Heading {
        visible: view.info !== null && !view.detailSection
        level: 4
        text: i18n("System overview")
    }

    CardGrid {
        visible: view.info !== null && (!view.detailSection || view.overviewDetail)

        Card {
            section: "hardware"
            title: i18n("Hardware")
            overviewIcon: "cpu"
            overviewIconFallback: "computer"
            readonly property var inventory: view.info?.hardware
            value: [inventory?.manufacturer, inventory?.model].filter(Boolean).join(" ")
                || view.info?.cpu?.model || i18n("Hardware details")
            detail: view.info ? [view.info.cpu.model
                                     ? i18n("Processor: %1 (%2 logical CPUs)", view.info.cpu.model, view.info.cpu.cores)
                                     : i18n("Logical CPUs: %1", view.info.cpu.cores),
                                 i18n("System memory: %1", view.size(view.info.memory.total)),
                                 ...Array.from(new Set([...(inventory?.graphics ?? []), ...view.info.gpus.map(gpu => gpu.name)]))
                                    .map(name => i18n("Graphics: %1", name)),
                                 inventory?.board ? i18n("Motherboard: %1", inventory.board) : "",
                                 inventory?.firmware ? i18n("Firmware version: %1", inventory.firmware) : ""]
                               .filter(Boolean).join("\n") : ""
        }

        Card {
            section: "os"
            title: i18n("Operating system")
            overviewIcon: view.info?.os?.logo || overviewIconFallback
            available: !!view.info?.os
            value: view.info?.os?.name ?? ""
            detail: view.info?.os ? [view.info.os.version ? i18n("Version: %1", view.info.os.version) : "",
                                     i18n("Kernel: %1", view.info.os.kernel),
                                     i18n("Architecture: %1", view.info.os.architecture),
                                     view.info.os.desktop ? i18n("Desktop: %1", view.info.os.desktop) : "",
                                     view.info.os.session ? i18n("Session: %1", view.info.os.session) : ""]
                                   .filter(label => label.length > 0).join("\n") : ""
        }

        Card {
            section: "uptime"
            available: !!view.info?.uptime_seconds
            title: i18n("Uptime")
            uptimeFraction: view.info?.uptime_seconds ? Math.min(1, view.info.uptime_seconds / 86400) : -1
            value: view.info ? view.uptime(view.info.uptime_seconds) : ""
            detail: {
                if (!view.info?.uptime_seconds)
                    return "";
                const started = new Date(Date.now() - view.info.uptime_seconds * 1000);
                const reasons = {
                    reboot: i18n("Orderly reboot"),
                    poweroff: i18n("Powered on after an orderly shutdown"),
                    kernel_panic: i18n("Kernel panic recorded before this boot")
                };
                const reason = reasons[view.info.last_restart] ?? i18n("Unknown from the available system journal");
                return i18n("Started %1", started.toLocaleString(Qt.locale(), Locale.ShortFormat))
                    + "\n" + i18n("Last restart: %1", reason);
            }
        }
    }

    Kirigami.Heading {
        visible: view.detailSection === "hardware" && (view.info?.hardware?.drives?.length ?? 0) > 0
        level: 5
        text: i18n("Physical drives")
    }

    Repeater {
        model: view.detailSection === "hardware" ? view.info?.hardware?.drives ?? [] : []

        ColumnLayout {
            required property var modelData
            Layout.fillWidth: true
            spacing: 2

            PlasmaComponents3.Label {
                Layout.fillWidth: true
                text: modelData.model || modelData.device
                wrapMode: Text.Wrap
            }

            PlasmaComponents3.Label {
                Layout.fillWidth: true
                text: [modelData.model ? modelData.device : "", view.size(modelData.total),
                       modelData.rotational === 1 ? i18n("Rotational") :
                       modelData.rotational === 0 ? i18n("Non-rotational") : ""].filter(Boolean).join(" · ")
                font: Kirigami.Theme.smallFont
                opacity: 0.75
                wrapMode: Text.Wrap
            }
        }
    }

    Kirigami.Heading {
        visible: (view.detailSection === "hardware" || view.detailSection === "disk-activity")
            && (view.info?.disks?.length ?? 0) > 0
        level: 5
        text: view.detailSection === "hardware" ? i18n("Mounted storage") : i18n("Activity by device")
        opacity: 0.7
    }

    Repeater {
        model: view.detailSection === "hardware" || view.detailSection === "disk-activity" ? view.info?.disks ?? [] : []

        ColumnLayout {
            id: disk
            required property var modelData
            readonly property var activity: view.info?.history?.disk_by_device?.[modelData.device] ?? null
            Layout.fillWidth: true
            spacing: 2

            RowLayout {
                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    text: view.detailSection === "hardware"
                        ? [modelData.mount, modelData.device, modelData.filesystem].filter(Boolean).join(" · ")
                        : modelData.mount
                    elide: Text.ElideMiddle
                }
                PlasmaComponents3.Label {
                    text: view.detailSection === "hardware"
                        ? i18n("%1 free of %2", view.size(modelData.total - modelData.used), view.size(modelData.total))
                        : view.rate(disk.activity?.length ? disk.activity[disk.activity.length - 1] : null)
                    font: Kirigami.Theme.smallFont
                    opacity: 0.75
                }
            }
            QQC2.ProgressBar {
                Layout.fillWidth: true
                visible: view.detailSection === "hardware"
                from: 0
                to: Math.max(1, modelData.total)
                value: modelData.used
            }
            Sparkline {
                visible: view.detailSection === "disk-activity" && disk.activity !== null
                values: disk.activity || []
                maximum: 0
            }
        }
    }

    component MemoryUsage: ColumnLayout {
        id: usage
        required property string label
        required property var used
        required property var total
        required property string totalLabel
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing

        PlasmaComponents3.Label {
            Layout.fillWidth: true
            text: usage.label
            wrapMode: Text.Wrap
        }

        PlasmaComponents3.Label {
            Layout.fillWidth: true
            text: i18n("%1 used · %2", view.size(usage.used), usage.totalLabel)
            font: Kirigami.Theme.smallFont
            wrapMode: Text.Wrap
        }

        QQC2.ProgressBar {
            Layout.fillWidth: true
            from: 0
            to: Math.max(1, usage.total ?? 0)
            value: Math.min(usage.used ?? 0, usage.total ?? 0)
            Accessible.name: usage.label
        }
    }

    Repeater {
        model: view.detailSection === "memory" ? (view.info?.gpus ?? []).filter(gpu =>
            (gpu.memory_total > 0 && gpu.memory_used != null)
            || (gpu.shared_total > 0 && gpu.shared_used != null)) : []

        ColumnLayout {
            id: gpuMemory
            required property var modelData
            Layout.fillWidth: true

            Kirigami.Heading {
                Layout.fillWidth: true
                level: 5
                text: i18n("GPU memory · %1", gpuMemory.modelData.name)
                wrapMode: Text.Wrap
            }

            MemoryUsage {
                objectName: "memoryVram"
                visible: total > 0 && used != null
                label: i18n("Graphics memory (VRAM)")
                used: gpuMemory.modelData.memory_used
                total: gpuMemory.modelData.memory_total
                totalLabel: i18n("%1 total", view.size(total))
            }

            MemoryUsage {
                objectName: "memorySharedGpu"
                visible: total > 0 && used != null
                label: i18n("System RAM used by the GPU")
                used: gpuMemory.modelData.shared_used
                total: gpuMemory.modelData.shared_total
                totalLabel: i18n("%1 driver limit", view.size(total))
            }

            PlasmaComponents3.Label {
                Layout.fillWidth: true
                visible: gpuMemory.modelData.shared_total > 0 && gpuMemory.modelData.shared_used != null
                text: i18n("This usage is part of system RAM.")
                font: Kirigami.Theme.smallFont
                opacity: 0.75
                wrapMode: Text.Wrap
            }
        }
    }

    RowLayout {
        visible: view.programsVisible
        Layout.fillWidth: true
        Layout.topMargin: Kirigami.Units.largeSpacing
        spacing: Kirigami.Units.smallSpacing

        Kirigami.Heading {
            Layout.fillWidth: true
            level: 5
            text: i18n("Programs")
            opacity: 0.7
        }

        Repeater {
            model: [
                { key: "user", label: i18n("User"), width: view.userColumnWidth },
                { key: "cpu", label: i18n("CPU"), width: view.cpuColumnWidth },
                { key: "memory", label: i18n("Memory"), width: view.memoryColumnWidth }
            ]

            PlasmaComponents3.ToolButton {
                required property var modelData
                readonly property bool sorted: view.sort === modelData.key
                objectName: "systemSort-" + modelData.key
                Layout.preferredWidth: modelData.width
                text: !sorted ? modelData.label : (view.sortDescending
                    ? i18n("%1 ↓", modelData.label) : i18n("%1 ↑", modelData.label))
                Accessible.name: !sorted ? i18n("Sort by %1", modelData.label)
                    : (view.sortDescending ? i18n("%1, descending", modelData.label)
                                           : i18n("%1, ascending", modelData.label))
                onClicked: view.sortPrograms(modelData.key)
            }
        }

        Item { Layout.preferredWidth: Kirigami.Units.gridUnit * 2 }
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
                    text: program.modelData.name
                    elide: Text.ElideRight
                    opacity: program.modelData.mine ? 1 : 0.7
                }
                PlasmaComponents3.Label {
                    Layout.preferredWidth: view.userColumnWidth
                    text: program.modelData.user
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    font: Kirigami.Theme.smallFont
                }
                PlasmaComponents3.Label {
                    Layout.preferredWidth: view.cpuColumnWidth
                    horizontalAlignment: Text.AlignRight
                    text: program.modelData.cpu_percent.toFixed(1) + "%"
                    font: Kirigami.Theme.smallFont
                }
                PlasmaComponents3.Label {
                    Layout.preferredWidth: view.memoryColumnWidth
                    horizontalAlignment: Text.AlignRight
                    text: view.size(program.modelData.memory)
                    font: Kirigami.Theme.smallFont
                }
                PlasmaComponents3.ToolButton {
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 2
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
