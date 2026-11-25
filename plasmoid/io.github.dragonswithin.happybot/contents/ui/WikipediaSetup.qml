/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

/**
 * The "Offline Wikipedia" row of the Search & Tools page (SetupTools.qml):
 * read Wikipedia without the internet, in Happy Bot's Wikipedia finder and
 * by the AI.
 *
 * It shows what is in use (`GET /wikipedia`: the archive, its size and
 * build, where it is) or that nothing is, and offers "Set up…", which lists
 * the choices (`POST /wikipedia/choices`, src/happy_bot/wikipedia_setup.py):
 * Wikipedia archives already on this computer, then Kiwix's sizes for the
 * user's language to download, each with its size, whether it fits on the
 * disk, and the recommended one marked. "Use this" or "Download" sends the
 * pick with the "Keep it up to date" box (`POST /wikipedia/use`). A
 * download runs in the daemon's background; while it does, a progress bar
 * and Stop show here, refreshed every `pollMs` (`POST /wikipedia/cancel`
 * keeps what was downloaded for next time). Once set up, "Keep it up to
 * date" switches the monthly update on or off (`POST /wikipedia/auto-update`),
 * unless another program keeps the archives current, which it then says;
 * "Turn off" removes the reader and keeps the archives (`POST /wikipedia/off`).
 *
 * Every change is made by the daemon, which also changes the settings, so
 * after each one (and when a download finishes) the page's settings are read
 * again (`page.reload`); a later save from the page then cannot put old ones
 * back. `page` is the page's DaemonSettings.qml.
 */
ColumnLayout {
    id: wiki

    required property var page

    property var info: ({ set_up: false, archives: [], download: { state: "idle" } })
    property bool choosing: false
    property bool loadingChoices: false
    property var offer: ({ found: [], downloads: [], free: 0, problem: "" })
    property bool keepUpdated: true
    property string busyId: ""
    property string problem: ""
    readonly property bool downloading: (info.download || {}).state === "downloading" || (info.download || {}).state === "verifying"
    readonly property int pollMs: 2000

    spacing: Kirigami.Units.smallSpacing

    function gigabytes(bytes) {
        return Math.max(0.1, Math.round(bytes / 1024 / 1024 / 1024 * 10) / 10);
    }

    function flavourName(flavour) {
        switch (flavour) {
        case "mini": return i18n("introductions only");
        case "nopic": return i18n("every article, no pictures");
        default: return i18n("everything, with pictures");
        }
    }

    function refresh() {
        const wasDownloading = wiki.downloading;
        wiki.page.client.request("GET", "/wikipedia", null, function(data) {
            wiki.info = data;
            if (wasDownloading && !wiki.downloading) {
                wiki.page.reload();
            }
        }, function(data) {});
    }

    function loadChoices() {
        wiki.loadingChoices = true;
        wiki.page.client.request("POST", "/wikipedia/choices", {}, function(data) {
            wiki.loadingChoices = false;
            wiki.offer = data;
        }, function(data) {
            wiki.loadingChoices = false;
            wiki.problem = data.error || i18n("Could not look for Wikipedia");
        });
    }

    function call(path, body, id, after) {
        wiki.busyId = id;
        wiki.problem = "";
        wiki.page.client.request("POST", path, body, function(data) {
            wiki.busyId = "";
            if (data.message) {
                wiki.page.report(data.message, false);
            }
            wiki.page.reload();
            wiki.refresh();
            if (after) {
                after(data);
            }
        }, function(data) {
            wiki.busyId = "";
            wiki.problem = data.error || i18n("That did not work");
            wiki.refresh();
        });
    }

    Component.onCompleted: refresh()

    Timer {
        interval: wiki.pollMs
        repeat: true
        running: wiki.downloading
        onTriggered: wiki.refresh()
    }

    QQC2.Label {
        Layout.maximumWidth: Kirigami.Units.gridUnit * 26
        wrapMode: Text.Wrap
        text: wiki.info.set_up && wiki.info.archives.length > 0
            ? i18n("Using %1 (%2, %3 GB, from %4) in %5.", wiki.info.archives[0].book.replace(/_/g, " "),
                   wiki.flavourName(wiki.info.archives[0].flavour), wiki.gigabytes(wiki.info.archives[0].size),
                   wiki.info.archives[0].build, wiki.info.folder)
            : i18n("Read Wikipedia without the internet: in Happy Bot's Wikipedia search, and for the AI's answers.")
    }

    RowLayout {
        spacing: Kirigami.Units.smallSpacing

        QQC2.Button {
            text: i18n("Set up…")
            icon.name: "run-build-configure"
            checkable: true
            checked: wiki.choosing
            enabled: !wiki.downloading
            onToggled: {
                wiki.choosing = checked;
                if (checked) {
                    wiki.loadChoices();
                }
            }
        }

        QQC2.Button {
            visible: wiki.info.set_up
            text: i18n("Turn off")
            icon.name: "edit-delete-remove"
            enabled: wiki.busyId === ""
            onClicked: wiki.call("/wikipedia/off", {}, "off")
        }
    }

    QQC2.CheckBox {
        visible: wiki.info.set_up
        text: i18n("Keep it up to date (Happy Bot checks once a month)")
        checked: wiki.info.auto_update === true
        enabled: !(wiki.info.updated_elsewhere || "").length && wiki.busyId === ""
        onToggled: wiki.call("/wikipedia/auto-update", { enabled: checked }, "auto")
    }

    QQC2.Label {
        visible: wiki.info.set_up && (wiki.info.updated_elsewhere || "").length > 0
        Layout.maximumWidth: Kirigami.Units.gridUnit * 26
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
        text: wiki.info.updated_elsewhere || ""
    }

    // A download under way, or how the last one ended.
    ColumnLayout {
        visible: wiki.downloading || (wiki.info.download || {}).state === "failed"
        Layout.maximumWidth: Kirigami.Units.gridUnit * 26
        spacing: Kirigami.Units.smallSpacing

        RowLayout {
            visible: wiki.downloading
            spacing: Kirigami.Units.smallSpacing

            QQC2.ProgressBar {
                Layout.fillWidth: true
                from: 0
                to: Math.max(1, (wiki.info.download || {}).total_bytes || 1)
                value: (wiki.info.download || {}).done_bytes || 0
                indeterminate: !((wiki.info.download || {}).total_bytes > 0)
            }

            QQC2.Button {
                text: i18n("Stop")
                icon.name: "media-playback-stop"
                onClicked: wiki.call("/wikipedia/cancel", {}, "cancel")
            }
        }

        QQC2.Label {
            visible: wiki.downloading
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            font: Kirigami.Theme.smallFont
            text: (wiki.info.download || {}).state === "verifying"
                ? i18n("Checking the download…")
                : i18n("Downloading %1 of %2 GB. It carries on if you close this window.",
                       wiki.gigabytes((wiki.info.download || {}).done_bytes || 0),
                       wiki.gigabytes((wiki.info.download || {}).total_bytes || 0))
        }

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: (wiki.info.download || {}).state === "failed"
            type: Kirigami.MessageType.Warning
            text: (wiki.info.download || {}).message || ""
        }
    }

    Kirigami.InlineMessage {
        Layout.maximumWidth: Kirigami.Units.gridUnit * 26
        Layout.fillWidth: true
        visible: wiki.problem.length > 0
        type: Kirigami.MessageType.Error
        text: wiki.problem
    }

    // The choices, under "Set up…".
    ColumnLayout {
        visible: wiki.choosing
        Layout.leftMargin: Kirigami.Units.gridUnit
        Layout.maximumWidth: Kirigami.Units.gridUnit * 26
        spacing: Kirigami.Units.largeSpacing

        RowLayout {
            visible: wiki.loadingChoices
            spacing: Kirigami.Units.smallSpacing

            QQC2.BusyIndicator {
                running: wiki.loadingChoices
                Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                Layout.preferredHeight: Kirigami.Units.iconSizes.medium
            }

            QQC2.Label {
                text: i18n("Looking for Wikipedia on this computer and what Kiwix offers…")
            }
        }

        QQC2.CheckBox {
            visible: !wiki.loadingChoices
            text: i18n("Keep it up to date")
            checked: wiki.keepUpdated
            onToggled: wiki.keepUpdated = checked
        }

        Repeater {
            model: wiki.loadingChoices ? [] : wiki.offer.found

            ColumnLayout {
                id: found
                required property var modelData
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                RowLayout {
                    Kirigami.Heading {
                        level: 4
                        text: i18n("Already on this computer")
                    }
                    QQC2.Label {
                        text: i18n("Recommended")
                        color: Kirigami.Theme.positiveTextColor
                        font: Kirigami.Theme.smallFont
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                    QQC2.Button {
                        text: wiki.busyId === found.modelData.id ? i18n("Setting up…") : i18n("Use this")
                        icon.name: "dialog-ok-apply"
                        highlighted: true
                        enabled: wiki.busyId === ""
                        onClicked: wiki.call("/wikipedia/use", { choice: found.modelData.id, auto_update: wiki.keepUpdated },
                                             found.modelData.id, () => wiki.choosing = false)
                    }
                }

                QQC2.Label {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    text: i18n("%1 in %2 (%3 GB). Nothing to download.",
                               found.modelData.archives.map(item => item.book.replace(/_/g, " ") + " " + item.build).join(", "),
                               found.modelData.folder, wiki.gigabytes(found.modelData.size))
                }

                QQC2.Label {
                    visible: found.modelData.updated_elsewhere.length > 0
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    font: Kirigami.Theme.smallFont
                    opacity: 0.7
                    text: found.modelData.updated_elsewhere
                }
            }
        }

        Repeater {
            model: wiki.loadingChoices ? [] : wiki.offer.downloads

            ColumnLayout {
                id: download
                required property var modelData
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                RowLayout {
                    Kirigami.Heading {
                        level: 4
                        text: download.modelData.title
                    }
                    QQC2.Label {
                        visible: download.modelData.recommended
                        text: i18n("Recommended")
                        color: Kirigami.Theme.positiveTextColor
                        font: Kirigami.Theme.smallFont
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                    QQC2.Button {
                        text: i18n("Download %1 GB", wiki.gigabytes(download.modelData.size))
                        icon.name: "download"
                        highlighted: download.modelData.recommended
                        enabled: download.modelData.fits && wiki.busyId === "" && !wiki.downloading
                        onClicked: wiki.call("/wikipedia/use", { choice: download.modelData.id, auto_update: wiki.keepUpdated },
                                             download.modelData.id, () => wiki.choosing = false)
                    }
                }

                QQC2.Label {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    text: download.modelData.fits ? download.modelData.detail
                        : i18n("%1 It does not fit: %2 GB are free.", download.modelData.detail, wiki.gigabytes(wiki.offer.free))
                }
            }
        }

        QQC2.Label {
            visible: !wiki.loadingChoices && (wiki.offer.problem || "").length > 0
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            text: wiki.offer.problem || ""
        }

        QQC2.Label {
            visible: !wiki.loadingChoices
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            text: i18n("Downloads come from Kiwix (kiwix.org) and are checked before use. They go to %1.", wiki.offer.folder || "")
        }
    }
}
