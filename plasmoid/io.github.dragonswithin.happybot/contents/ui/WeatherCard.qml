/*
    SPDX-License-Identifier: MIT
*/

pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3

/**
 * The weather at a glance, under the weather step in TranscriptEntry.qml:
 * the place, a large condition icon with the temperature now, what it
 * feels like and the wind, then one column per day (weekday, icon, low and
 * high, chance of rain).
 *
 * `weather` is the card the daemon sends with the weather tool's result
 * (`weather_card` in src/happy_bot/tools/weather.py): `{place, now:
 * {temperature, feels, conditions, wind}, days: [{date, low, high,
 * conditions, rain, sunrise, sunset}]}`, numbers as text in °C and km/h.
 * `iconFor` turns the service's condition words into the desktop's weather
 * icons. The card keeps no state.
 */
ColumnLayout {
    id: card

    required property var weather

    spacing: Kirigami.Units.smallSpacing

    function iconFor(conditions) {
        const words = String(conditions || "");
        if (words.indexOf("thunder") !== -1) return "weather-storm";
        if (words.indexOf("snow") !== -1) return "weather-snow";
        if (words.indexOf("freezing") !== -1) return "weather-freezing-rain";
        if (words.indexOf("shower") !== -1 || words.indexOf("drizzle") !== -1) return "weather-showers-scattered";
        if (words.indexOf("rain") !== -1) return "weather-showers";
        if (words.indexOf("fog") !== -1) return "weather-fog";
        if (words === "clear" || words === "mostly clear") return "weather-clear";
        if (words === "partly cloudy") return "weather-few-clouds";
        if (words === "overcast") return "weather-overcast";
        return "weather-clouds";
    }

    function weekday(date) {
        const parts = String(date).split("-").map(Number);
        return Qt.locale().dayName(new Date(parts[0], parts[1] - 1, parts[2]).getDay(), Locale.ShortFormat);
    }

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        text: card.weather.place
        elide: Text.ElideRight
        font: Kirigami.Theme.smallFont
        opacity: 0.7
    }

    RowLayout {
        spacing: Kirigami.Units.largeSpacing

        Kirigami.Icon {
            source: card.iconFor(card.weather.now.conditions)
            Layout.preferredWidth: Kirigami.Units.iconSizes.large
            Layout.preferredHeight: Kirigami.Units.iconSizes.large
        }

        ColumnLayout {
            spacing: 0

            Kirigami.Heading {
                level: 1
                text: i18n("%1°C", Math.round(Number(card.weather.now.temperature)))
            }

            PlasmaComponents3.Label {
                text: i18n("%1, feels like %2°C, wind %3 km/h", card.weather.now.conditions,
                           Math.round(Number(card.weather.now.feels)), Math.round(Number(card.weather.now.wind)))
                opacity: 0.8
            }
        }
    }

    RowLayout {
        spacing: Kirigami.Units.largeSpacing
        visible: card.weather.days.length > 0

        Repeater {
            model: card.weather.days

            ColumnLayout {
                id: day

                required property var modelData

                spacing: 0
                Accessible.name: i18n("%1: %2, %3 to %4°C, %5% chance of rain", card.weekday(modelData.date),
                                      modelData.conditions, modelData.low, modelData.high, modelData.rain)

                PlasmaComponents3.Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: card.weekday(day.modelData.date)
                    font: Kirigami.Theme.smallFont
                }

                Kirigami.Icon {
                    Layout.alignment: Qt.AlignHCenter
                    source: card.iconFor(day.modelData.conditions)
                    Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                    Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                }

                PlasmaComponents3.Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: i18n("%1° / %2°", Math.round(Number(day.modelData.low)), Math.round(Number(day.modelData.high)))
                    font: Kirigami.Theme.smallFont
                }

                PlasmaComponents3.Label {
                    Layout.alignment: Qt.AlignHCenter
                    visible: day.modelData.rain !== "?" && Number(day.modelData.rain) > 0
                    text: i18n("%1% rain", day.modelData.rain)
                    font: Kirigami.Theme.smallFont
                    opacity: 0.7
                }
            }
        }
    }
}
