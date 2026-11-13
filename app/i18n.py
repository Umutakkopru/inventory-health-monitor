"""German and English UI strings, and number and date formatting per language.

Keys are dotted (`overview.kpi.critical`). Status, alert-column and threshold labels come
from `inventory_monitor.report`, which needs them for the Excel export, so every label
exists once. `t()` returns the string for the current language; a missing key returns the
key itself, or raises when the environment variable I18N_STRICT is set (as in the tests).
"""

import math
import os

import pandas as pd

from app import state
from inventory_monitor.report import COLUMN_LABELS, STATUS_LABELS, THRESHOLD_LABELS

STRICT_ENV = "I18N_STRICT"
MISSING = "–"
UNLIMITED_COVERAGE = "> 365"
# Soft hyphens (\\u00ad) in long German labels let narrow cards break words at a syllable.

_TEXT: dict[str, dict[str, str]] = {
    "de": {
        "app.title": "Bestandsmonitor",
        "nav.overview": "Übersicht",
        "nav.alerts": "Warnungen",
        "nav.material_detail": "Materialdetail",
        "nav.abc_xyz": "ABC/XYZ",
        "nav.data_quality": "Datenqualität",
        "nav.methodology": "Methodik",
        "sidebar.language": "Sprache / Language",
        "sidebar.plants": "Werk",
        "sidebar.as_of": "Stichtag",
        "sidebar.as_of_help": (
            "Alle Kennzahlen werden mit Daten bis einschließlich diesem Tag berechnet."
        ),
        "sidebar.thresholds": "Schwellenwerte",
        "sidebar.reset": "Standardwerte",
        "sidebar.synthetic_note": "Alle Daten sind synthetisch und dienen nur der Demonstration.",
        "lang.de": "Deutsch",
        "lang.en": "English",
        "common.empty": "Für die aktuelle Auswahl gibt es keine Daten.",
        "common.no_plant": "Bitte mindestens ein Werk auswählen.",
        "abc.title": "ABC/XYZ-Analyse",
        "abc.caption": (
            "ABC: Anteil am Verbrauchswert je Werk. XYZ: Regelmäßigkeit des Wochenbedarfs."
        ),
        "abc.abc.A": "A (hoher Wert)",
        "abc.abc.B": "B (mittlerer Wert)",
        "abc.abc.C": "C (geringer Wert)",
        "abc.xyz.X": "X (gleichmäßig)",
        "abc.xyz.Y": "Y (schwankend)",
        "abc.xyz.Z": "Z (unregelmäßig)",
        "abc.matrix.title": "Materialien je ABC/XYZ-Klasse",
        "abc.matrix.x": "XYZ-Klasse (Regelmäßigkeit)",
        "abc.matrix.y": "ABC-Klasse (Verbrauchswert)",
        "abc.matrix.cell": "{count} Mat.<br>{value}",
        "abc.matrix.hover": "%{y} · %{x}<br>%{z} Materialien<br>Bestandswert %{customdata}",
        "abc.pareto.plant": "Werk",
        "abc.pareto.title": "Pareto-Diagramm des Verbrauchswerts",
        "abc.pareto.x": "Materialien, absteigend nach Verbrauchswert",
        "abc.pareto.y": "Verbrauchswert 12 Monate (EUR)",
        "abc.pareto.y2": "Kumulierter Anteil",
        "abc.pareto.value": "Verbrauchswert",
        "abc.pareto.share": "Kumulierter Anteil",
        "abc.pareto.hover": "%{x} · %{customdata[0]}<br>Klasse %{customdata[1]}<br>%{y:,.0f} €",
        "abc.pareto.share_hover": "%{x}: %{y:.1%} kumuliert",
        "abc.pareto.caption": "Gepunktete Linien: Klassengrenzen A und B. Balkenfarbe: ABC-Klasse.",
        "abc.dev.title": "Stammdaten mit starker Abweichung",
        "abc.dev.caption": (
            "Mindestbestand im Materialstamm weicht um mindestens 50 % vom berechneten "
            "Sicherheitsbestand ab – ein Hinweis auf veraltete Parameter."
        ),
        "abc.dev.master": "Mindestbestand (Stamm)",
        "abc.dev.calc": "Sicherheitsbestand (berechnet)",
        "abc.dev.deviation": "Abweichung",
        "dq.title": "Datenqualität",
        "dq.caption": (
            "Ergebnisse der Prüfungen beim Einlesen. Jede Auffälligkeit wurde repariert, "
            "verworfen oder markiert."
        ),
        "dq.check.DQ01": "Fehlender Bestandstag",
        "dq.check.DQ02": "Negativer Bestand",
        "dq.check.DQ03": "Doppelter Bestandssatz",
        "dq.check.DQ04": "Wareneingang für unbekanntes Material",
        "dq.check.DQ05": "Bestand für unbekanntes Material",
        "dq.check.DQ06": "Wareneingangsmenge null oder negativ",
        "dq.check.DQ07": "Materialnummer repariert",
        "dq.check.DQ08": "Bestand gestiegen ohne Wareneingang",
        "dq.check.DQ09": "Mehrere Mengeneinheiten",
        "dq.check.DQ10": "Preis oder Wiederbeschaffungszeit fehlt",
        "dq.check.DQ11": "Wareneingang außerhalb des Zeitraums",
        "dq.severity.error": "Fehler",
        "dq.severity.warning": "Warnung",
        "dq.severity.info": "Hinweis",
        "dq.action.gap_imputed": "Lücke geschätzt",
        "dq.action.treated_as_missing": "Als fehlender Tag behandelt",
        "dq.action.kept_last": "Letzter Satz behalten",
        "dq.action.receipt_dropped": "Wareneingang verworfen",
        "dq.action.rows_dropped": "Zeilen verworfen",
        "dq.action.repaired": "Repariert",
        "dq.action.clipped_to_zero": "Für Statistik auf null gesetzt",
        "dq.action.master_unit_kept": "Stammdaten-Einheit verwendet",
        "dq.action.material_excluded": "Material ausgeschlossen",
        "dq.action.ignored": "Ignoriert",
        "dq.counts.title": "Auffälligkeiten je Prüfung",
        "dq.counts.x": "Anzahl Auffälligkeiten",
        "dq.counts.hover": "%{y}: %{x}",
        "dq.table.title": "Alle Auffälligkeiten",
        "dq.table.count": "{shown} von {total} Auffälligkeiten",
        "dq.table.checks": "Prüfung",
        "dq.table.search_hint": "Materialnummer",
        "dq.table.check": "Prüfung",
        "dq.table.severity": "Schwere",
        "dq.table.sheet": "Tabellenblatt",
        "dq.table.date": "Datum",
        "dq.table.detail": "Detail",
        "dq.table.action": "Maßnahme",
        "dq.score.title": "Datenqualität je Material",
        "dq.score.caption": (
            "Anteil der Tage, die beobachtet, nicht geschätzt und ohne Auffälligkeit sind. Die "
            "15 niedrigsten Werte."
        ),
        "dq.score.score": "Datenqualität",
        "method.title": "Methodik",
        "method.intro.title": "Worum es geht",
        "method.intro.body": (
            "Das Dashboard bewertet jedes Material je Werk automatisch: Droht ein **Engpass** "
            "oder liegt ein **Überbestand** vor? Grundlage sind nur die täglichen "
            "Lagerbestände, die Wareneingänge und der Materialstamm. Alle Kennzahlen gelten zum "
            "gewählten **Stichtag**; Daten danach werden nie verwendet."
        ),
        "method.data.title": "Daten und Annahmen",
        "method.data.body": (
            "- **Bestand** ist der Bestand am Tagesende. Ein Wareneingang mit Buchungsdatum *t* "
            "ist im Bestand von Tag *t* bereits enthalten.\n- Die Aufgabe nennt nur "
            "Lagerbestände und Wareneingänge. Den **Materialstamm** (Preis, "
            "Wiederbeschaffungszeit, Mindest- und Maximalbestand) setzen wir zusätzlich voraus. "
            "Mindest- und Maximalbestand dürfen fehlen.\n- Lagerorte werden je Material und "
            "Werk addiert. Fehlt an einem Tag ein Lagerort, gilt der ganze Tag als fehlend, "
            "weil eine Teilsumme wie ein plötzlicher Bestandsabbau aussähe.\n- Alle Daten in "
            "dieser Demo sind **synthetisch** erzeugt."
        ),
        "method.consumption.title": "Abgeleiteter Verbrauch",
        "method.consumption.body": (
            "Für einen beobachteten Tag *d* mit vorherigem beobachtetem Tag *p*:\n\n`Abfluss = "
            "Bestand(p) + Wareneingänge in (p, d] − Bestand(d)`\n\nDer Abfluss wird gleichmäßig "
            "auf die *n* Tage von *p* bis *d* verteilt (bei einer Lücke *n* > 1, die Tage "
            "gelten dann als geschätzt). Negative Werte (Bestand stieg ohne gebuchten "
            "Wareneingang) werden gemeldet und für die Statistik auf null gesetzt. Der Wert ist "
            "ein **Nettoabfluss**: Er enthält auch Verschrottung, Umlagerungen und "
            "Inventurdifferenzen."
        ),
        "method.kpis.title": "Kennzahlen",
        "method.kpis.body": (
            "| Kennzahl | Berechnung | Wozu |\n|---|---|---|\n| Ø Tagesverbrauch | Mittelwert "
            "des Verbrauchs der letzten {demand_window} Tage | Grundlage für Reichweite und "
            "Meldebestand |\n| Schwankung σ | Standardabweichung des **Wochen**bedarfs der "
            "letzten {variability_weeks} vollständigen Wochen | Wochenwerte, weil Wochenenden "
            "ohne Verbrauch eine Tagesstreuung künstlich aufblähen |\n| Sicherheitsbestand | `z "
            "× σ × √(WBZ / 7)`, WBZ = Wiederbeschaffungszeit, z aus dem Servicegrad der "
            "ABC-Klasse (A {sl_a}, B {sl_b}, C "
            "{sl_c}) | Puffer gegen Bedarfsschwankungen während der Wiederbeschaffung |\n| "
            "Meldebestand | `Ø Tagesverbrauch × WBZ + Sicherheitsbestand` | Ab hier sollte "
            "nachbestellt werden |\n| Reichweite | `Bestand / Ø Tagesverbrauch` (ohne "
            "Verbrauch: > 365) | Wie viele Tage der Bestand reicht |\n| Maximalbestand (Ziel) | "
            "`Ø Tagesverbrauch × Ziel-Reichweite` (A {over_a}, B {over_b}, C {over_c} Tage) | "
            "Grenze zum Überbestand |\n\nIst im Materialstamm ein Mindest- oder Maximalbestand "
            "gepflegt, **hat der Stammwert Vorrang**. Der berechnete Wert wird zum Vergleich "
            "trotzdem gezeigt (Seite ABC/XYZ). Deshalb wirken die Servicegrad-Regler nur auf "
            "Materialien ohne Mindestbestand."
        ),
        "method.classes.title": "ABC- und XYZ-Analyse",
        "method.classes.body": (
            "- **ABC** je Werk nach Verbrauchswert der letzten 12 Monate (Menge × Preis): A bis "
            "{abc_a} des kumulierten Werts, B bis {abc_b}, C der Rest. Das Material, das eine "
            "Grenze überschreitet, gehört noch zur höheren Klasse.\n- **XYZ** nach "
            "Variationskoeffizient des Wochenbedarfs (σ / Mittelwert): X unter {xyz_x}, Y bis "
            "{xyz_y}, Z darüber oder ohne verwertbaren Bedarf."
        ),
        "method.status.title": "Status-Regeln",
        "method.status.body": (
            "Jedes Material erhält genau einen Status; die Regeln werden in dieser Reihenfolge "
            "geprüft, die erste passende gilt:\n\n1. **Zu wenig Daten:** weniger als "
            "{min_history} Tage Historie.\n2. **Inaktiv:** Bestand null und seit mindestens "
            "{dead_days} Tagen kein Verbrauch.\n3. **Engpass (kritisch):** Bestand null oder "
            "unter dem Sicherheitsbestand.\n4. **Meldebestand unterschritten:** Bestand unter "
            "dem Meldebestand.\n5. **Ladenhüter:** Bestand vorhanden, aber seit mindestens "
            "{dead_days} Tagen kein Verbrauch.\n6. **Überbestand:** Bestand über dem "
            "Maximalbestand.\n7. **In Ordnung:** alles andere.\n\nBewusst **keine** Regel "
            "„Reichweite unter Wiederbeschaffungszeit ist kritisch“: Bei einer "
            "Bestellpunktpolitik liegt jedes gesunde Material in jedem Zyklus eine Weile "
            "darunter, während die Nachlieferung unterwegs ist.\n\nAuffälligkeiten (Bedarf oder "
            "Wareneingang über Q3 + {iqr} × IQR der Historie) werden zusätzlich markiert, "
            "ändern den Status aber nicht."
        ),
        "method.projection.title": "Projektion",
        "method.projection.body": (
            "Die Projektion zeigt, wie sich der Bestand entwickelt, **wenn kein weiterer "
            "Wareneingang eintrifft**. Sie ist keine Bedarfsprognose. Verbrauchsrate: "
            "exponentiell geglätteter Wochenbedarf (Glättungsfaktor {alpha}) geteilt durch 7. "
            "Band: ± σ × √(Tage / 7). Horizont: {horizon} Tage."
        ),
        "method.quality.title": "Datenqualität",
        "method.quality.body": (
            "Beim Einlesen laufen elf Prüfungen (DQ01–DQ11), etwa auf fehlende Tage, negative "
            "Bestände, Dubletten oder verlorene führende Nullen in Materialnummern. "
            "Strukturelle Fehler (fehlendes Blatt, fehlende Spalte) stoppen das Einlesen mit "
            "einer klaren Meldung; fehlerhafte Zeilen werden repariert, verworfen oder "
            "markiert. Der Datenqualitätswert je Material ist der Anteil der Tage, die "
            "beobachtet, nicht geschätzt und ohne Auffälligkeit sind."
        ),
        "method.limits.title": "Grenzen",
        "method.limits.body": (
            "- **Keine offenen Bestellungen:** „Meldebestand unterschritten“ heißt daher "
            "„prüfen, ob eine Bestellung offen ist“, nicht „jetzt bestellen“. Mit Bestelldaten "
            "aus dem ERP ließe sich die Warnung gegen erwartete Zugänge verrechnen.\n- "
            "**Abgeleiteter Verbrauch** ist ein Nettoabfluss und enthält auch Verschrottung, "
            "Umlagerung und Inventurdifferenzen.\n- **Verdeckter Bedarf:** Bei Bestand null "
            "wird nichts verbraucht, auch wenn Bedarf bestand. Der Bedarf während eines "
            "Engpasses wird daher unterschätzt.\n- **Keine Bedarfsprognose:** Kennzahlen "
            "beruhen auf der jüngsten Vergangenheit; Saisonalität wird nicht modelliert.\n- "
            "**Synthetische Daten:** Zahlen und Materialien sind erfunden und dienen nur der "
            "Demonstration."
        ),
        "alerts.title": "Warnungen",
        "alerts.caption": (
            "Alle Materialien mit Kennzahlen, sortiert nach Dringlichkeit. "
            "Spaltenköpfe anklicken zum Sortieren, Zeile auswählen für Details."
        ),
        "alerts.filter.status": "Status",
        "alerts.filter.all": "Alle",
        "alerts.filter.search": "Suche",
        "alerts.filter.search_hint": "Materialnummer oder Kurztext",
        "alerts.count": "{shown} von {total} Materialien",
        "alerts.open_detail": "Details öffnen: {material}",
        "alerts.select_hint": "Eine Zeile auswählen, um das Materialdetail zu öffnen.",
        "alerts.download": "Excel-Export",
        "alerts.download_file": "Warnungen_{date}.xlsx",
        "detail.title": "Materialdetail",
        "detail.select": "Material",
        "detail.series.receipts": "Wareneingang",
        "detail.series.stock": "Bestand",
        "detail.series.missing": "Fehlender Tag (geschätzt)",
        "detail.series.consumption": "Abgeleiteter Verbrauch",
        "detail.series.projection": "Projektion ohne weiteren Wareneingang",
        "detail.series.band": "Schwankungsband (± 1 σ)",
        "detail.chart.title": "Bestandsverlauf {material} · Werk {plant}",
        "detail.chart.x": "Datum",
        "detail.chart.y_stock": "Bestand ({unit})",
        "detail.chart.y_consumption": "Verbrauch ({unit}/Tag)",
        "detail.chart.caption": (
            "Gestrichelt: Projektion, falls kein weiterer Wareneingang eintrifft – keine "
            "Bedarfsprognose. Kreuze markieren Tage ohne vollständigen Bestandssnapshot."
        ),
        "detail.fact.avg_demand": "Ø Verbrauch pro Tag",
        "detail.fact.sigma_weekly": "Schwankung pro Woche (σ)",
        "detail.fact.classes": "ABC / XYZ",
        "detail.fact.last_consumption": "Letzter Verbrauch",
        "detail.fact.dq_score": "Datenqualität",
        "detail.facts.title": "Kennzahlen",
        "detail.master.title": "Stammdaten",
        "detail.master.price": "Preis pro Einheit",
        "detail.master.lead_time": "Wiederbeschaffungszeit",
        "detail.master.min_stock": "Mindestbestand (Stamm)",
        "detail.master.max_stock": "Maximalbestand (Stamm)",
        "detail.master.safety_calc": "Sicherheitsbestand (berechnet)",
        "detail.master.deviation": "Abweichung Stamm vs. berechnet",
        "detail.days": "{days} Tage",
        "detail.anomaly": "Auffälligkeit: ungewöhnlicher Bedarf oder Wareneingang in letzter Zeit.",
        "detail.sloc.toggle": "Nach Lagerort aufteilen",
        "detail.sloc.name": "Lagerort {sloc}",
        "detail.sloc.title": "Bestand je Lagerort",
        "overview.title": "Engpässe und Überbestände auf einen Blick",
        "overview.subtitle": "Automatische Bewertung aller Materialien zum Stichtag {date}",
        "overview.kpi.critical": "Eng\u00adpässe (kritisch)",
        "overview.kpi.critical_help": "Bestand unter dem Sicherheitsbestand oder null.",
        "overview.kpi.warning": "Unter Melde\u00adbestand",
        "overview.kpi.warning_help": (
            "Bestand unter dem Meldebestand: prüfen, ob eine Bestellung offen ist."
        ),
        "overview.kpi.overstock": "Über\u00adbestände",
        "overview.kpi.overstock_help": "Bestand über dem Maximalbestand bzw. der Ziel-Reichweite.",
        "overview.kpi.dead_stock": "Laden\u00adhüter",
        "overview.kpi.dead_stock_help": "Bestand vorhanden, aber lange kein Verbrauch.",
        "overview.kpi.stock_value": "Bestandswert",
        "overview.kpi.stock_value_help": "Summe aus Bestand × Preis aller Materialien.",
        "overview.kpi.excess_value": "Gebundenes Kapital im Überbestand",
        "overview.kpi.excess_value_help": (
            "Wert oberhalb des Maximalbestands plus der gesamte Bestandswert der Ladenhüter."
        ),
        "overview.kpi.critical_proof": "Bestand < Sicherheits\u00adbestand",
        "overview.kpi.warning_proof": "Bestellung offen?",
        "overview.kpi.overstock_proof": "Bestand > Maximum",
        "overview.kpi.dead_stock_proof": "≥ {days} Tage ohne Verbrauch",
        "overview.kpi.stock_value_proof": "{count} Materialien",
        "overview.kpi.excess_value_proof": "Überbestand + Ladenhüter",
        "overview.plant_tag": "Werk {plant}",
        "overview.status_chart.title": "Materialien nach Status",
        "overview.status_chart.x": "Anzahl Materialien",
        "overview.status_chart.hover": "%{y}: %{x} Materialien",
        "overview.value_chart.title": "Bestandswert im Zeitverlauf",
        "overview.value_chart.x": "Datum",
        "overview.value_chart.y": "Bestandswert (EUR)",
        "overview.value_chart.hover": "%{{x|{date_format}}}: %{{y:,.0f}} €",
        "overview.top.title": "Die 10 dringendsten Materialien",
        "overview.top.caption": (
            "Sortiert nach Status, dann nach Wert im Risiko; Engpässe der Klasse A zuerst."
        ),
    },
    "en": {
        "app.title": "Inventory Monitor",
        "nav.overview": "Overview",
        "nav.alerts": "Alerts",
        "nav.material_detail": "Material detail",
        "nav.abc_xyz": "ABC/XYZ",
        "nav.data_quality": "Data quality",
        "nav.methodology": "Methodology",
        "sidebar.language": "Sprache / Language",
        "sidebar.plants": "Plant",
        "sidebar.as_of": "As-of date",
        "sidebar.as_of_help": "All figures are calculated from data up to and including this day.",
        "sidebar.thresholds": "Thresholds",
        "sidebar.reset": "Reset to defaults",
        "sidebar.synthetic_note": "All data is synthetic and for demonstration only.",
        "lang.de": "Deutsch",
        "lang.en": "English",
        "common.empty": "There is no data for the current selection.",
        "common.no_plant": "Please select at least one plant.",
        "abc.title": "ABC/XYZ analysis",
        "abc.caption": (
            "ABC: share of consumption value per plant. XYZ: regularity of weekly demand."
        ),
        "abc.abc.A": "A (high value)",
        "abc.abc.B": "B (medium value)",
        "abc.abc.C": "C (low value)",
        "abc.xyz.X": "X (steady)",
        "abc.xyz.Y": "Y (variable)",
        "abc.xyz.Z": "Z (irregular)",
        "abc.matrix.title": "Materials per ABC/XYZ class",
        "abc.matrix.x": "XYZ class (regularity)",
        "abc.matrix.y": "ABC class (consumption value)",
        "abc.matrix.cell": "{count} mat.<br>{value}",
        "abc.matrix.hover": "%{y} · %{x}<br>%{z} materials<br>Stock value %{customdata}",
        "abc.pareto.plant": "Plant",
        "abc.pareto.title": "Pareto chart of consumption value",
        "abc.pareto.x": "Materials, by consumption value, descending",
        "abc.pareto.y": "Consumption value 12 months (EUR)",
        "abc.pareto.y2": "Cumulative share",
        "abc.pareto.value": "Consumption value",
        "abc.pareto.share": "Cumulative share",
        "abc.pareto.hover": "%{x} · %{customdata[0]}<br>Class %{customdata[1]}<br>€%{y:,.0f}",
        "abc.pareto.share_hover": "%{x}: %{y:.1%} cumulative",
        "abc.pareto.caption": "Dotted lines: class boundaries A and B. Bar colour: ABC class.",
        "abc.dev.title": "Master data with a large deviation",
        "abc.dev.caption": (
            "The minimum stock in the material master deviates by at least 50% from the "
            "calculated safety stock – a sign of outdated parameters."
        ),
        "abc.dev.master": "Minimum stock (master)",
        "abc.dev.calc": "Safety stock (calculated)",
        "abc.dev.deviation": "Deviation",
        "dq.title": "Data quality",
        "dq.caption": (
            "Results of the checks run while reading the file. Every finding was repaired, "
            "dropped or flagged."
        ),
        "dq.check.DQ01": "Missing stock day",
        "dq.check.DQ02": "Negative stock",
        "dq.check.DQ03": "Duplicate stock row",
        "dq.check.DQ04": "Receipt for unknown material",
        "dq.check.DQ05": "Stock for unknown material",
        "dq.check.DQ06": "Receipt quantity zero or negative",
        "dq.check.DQ07": "Material number repaired",
        "dq.check.DQ08": "Stock rose without a receipt",
        "dq.check.DQ09": "Several units of measure",
        "dq.check.DQ10": "Price or lead time missing",
        "dq.check.DQ11": "Receipt outside the period",
        "dq.severity.error": "Error",
        "dq.severity.warning": "Warning",
        "dq.severity.info": "Info",
        "dq.action.gap_imputed": "Gap estimated",
        "dq.action.treated_as_missing": "Treated as a missing day",
        "dq.action.kept_last": "Last row kept",
        "dq.action.receipt_dropped": "Receipt dropped",
        "dq.action.rows_dropped": "Rows dropped",
        "dq.action.repaired": "Repaired",
        "dq.action.clipped_to_zero": "Set to zero for statistics",
        "dq.action.master_unit_kept": "Master-data unit used",
        "dq.action.material_excluded": "Material excluded",
        "dq.action.ignored": "Ignored",
        "dq.counts.title": "Findings per check",
        "dq.counts.x": "Number of findings",
        "dq.counts.hover": "%{y}: %{x}",
        "dq.table.title": "All findings",
        "dq.table.count": "{shown} of {total} findings",
        "dq.table.checks": "Check",
        "dq.table.search_hint": "Material number",
        "dq.table.check": "Check",
        "dq.table.severity": "Severity",
        "dq.table.sheet": "Sheet",
        "dq.table.date": "Date",
        "dq.table.detail": "Detail",
        "dq.table.action": "Action",
        "dq.score.title": "Data quality per material",
        "dq.score.caption": (
            "Share of days that are observed, not estimated and without findings. The 15 lowest "
            "values."
        ),
        "dq.score.score": "Data quality",
        "method.title": "Methodology",
        "method.intro.title": "What this is about",
        "method.intro.body": (
            "The dashboard assesses every material per plant automatically: is a **shortage** "
            "coming, or is there **overstock**? It uses only the daily stock levels, the goods "
            "receipts and the material master. All figures refer to the chosen **as-of date**; "
            "data after it is never used."
        ),
        "method.data.title": "Data and assumptions",
        "method.data.body": (
            "- **Stock** is the end-of-day stock. A receipt posted on day *t* is already "
            "included in the stock of day *t*.\n- The task mentions only stock levels and goods "
            "receipts. The **material master** (price, lead time, minimum and maximum stock) is "
            "our additional assumption. Minimum and maximum stock may be empty.\n- Storage "
            "locations are summed per material and plant. If one location is missing on a day, "
            "the whole day counts as missing, because a partial sum would look like a sudden "
            "drop in stock.\n- All data in this demo is **synthetic**."
        ),
        "method.consumption.title": "Derived consumption",
        "method.consumption.body": (
            "For an observed day *d* whose previous observed day is *p*:\n\n`outflow = stock(p) "
            "+ receipts in (p, d] − stock(d)`\n\nThe outflow is spread evenly over the *n* days "
            "from *p* to *d* (with a gap *n* > 1, and those days count as estimated). Negative "
            "values (stock rose without a booked receipt) are reported and set to zero for the "
            "statistics. The figure is a **net outflow**: it also contains scrap, transfers and "
            "inventory corrections."
        ),
        "method.kpis.title": "Key figures",
        "method.kpis.body": (
            "| Figure | Calculation | Why |\n|---|---|---|\n| Avg. daily consumption | Mean "
            "consumption over the last {demand_window} days | Basis for coverage and reorder "
            "point |\n| Variability σ | Standard deviation of **weekly** demand over the last "
            "{variability_weeks} complete weeks | Weekly values, because weekends without "
            "consumption would inflate a daily spread |\n| Safety stock | `z × σ × √(lead time "
            "/ 7)`, z from the service level of the ABC class (A {sl_a}, B {sl_b}, C {sl_c}) | "
            "Buffer against demand variation during replenishment |\n| Reorder point | `avg. "
            "daily consumption × lead time + safety stock` | Reorder from here on |\n| Coverage "
            "| `stock / avg. daily consumption` (no consumption: > 365) | How many days the "
            "stock lasts |\n| Maximum (target) | `avg. daily consumption × target coverage` (A "
            "{over_a}, B {over_b}, C {over_c} days) | Boundary to overstock |\n\nWhere the "
            "material master holds a minimum or maximum stock, **the master value takes "
            "precedence**. The calculated value is still shown for comparison (ABC/XYZ page). "
            "That is why the service-level sliders only affect materials without a minimum "
            "stock."
        ),
        "method.classes.title": "ABC and XYZ analysis",
        "method.classes.body": (
            "- **ABC** per plant by consumption value of the last 12 months (quantity × price): "
            "A up to {abc_a} of the cumulative value, B up to {abc_b}, C the rest. The material "
            "that crosses a boundary still belongs to the higher class.\n- **XYZ** by the "
            "coefficient of variation of weekly demand (σ / mean): X below {xyz_x}, Y up to "
            "{xyz_y}, Z above or without usable demand."
        ),
        "method.status.title": "Status rules",
        "method.status.body": (
            "Every material gets exactly one status; the rules are checked in this order and "
            "the first match wins:\n\n1. **Insufficient data:** less than {min_history} days of "
            "history.\n2. **Inactive:** zero stock and no consumption for at least {dead_days} "
            "days.\n3. **Shortage (critical):** stock zero or below safety stock.\n4. **Below "
            "reorder point:** stock below the reorder point.\n5. **Dead stock:** stock on hand, "
            "but no consumption for at least {dead_days} days.\n6. **Overstock:** stock above "
            "the maximum.\n7. **OK:** everything else.\n\nThere is deliberately **no** rule "
            "“coverage below lead time is critical”: under a reorder-point policy every healthy "
            "material spends part of each cycle below it while the replenishment is on its "
            "way.\n\nAnomalies (demand or receipt above Q3 + {iqr} × IQR of the history) are "
            "flagged in addition but never change the status."
        ),
        "method.projection.title": "Projection",
        "method.projection.body": (
            "The projection shows how the stock develops **if no further receipt arrives**. It "
            "is not a demand forecast. Consumption rate: exponentially smoothed weekly demand "
            "(smoothing factor {alpha}) divided by 7. Band: ± σ × √(days / 7). Horizon: "
            "{horizon} days."
        ),
        "method.quality.title": "Data quality",
        "method.quality.body": (
            "Eleven checks (DQ01–DQ11) run while reading the file, for example for missing "
            "days, negative stock, duplicates or lost leading zeros in material numbers. "
            "Structural errors (missing sheet or column) stop the import with a clear message; "
            "faulty rows are repaired, dropped or flagged. The data-quality score per material "
            "is the share of days that are observed, not estimated and without findings."
        ),
        "method.limits.title": "Limitations",
        "method.limits.body": (
            "- **No open purchase orders:** “below reorder point” therefore means “check that "
            "an order is open”, not “order now”. With order data from the ERP the warning could "
            "be netted against expected receipts.\n- **Derived consumption** is a net outflow "
            "and also contains scrap, transfers and inventory corrections.\n- **Hidden "
            "demand:** at zero stock nothing is consumed even if there was demand, so demand "
            "during a shortage is underestimated.\n- **No demand forecast:** figures rest on "
            "the recent past; seasonality is not modelled.\n- **Synthetic data:** numbers and "
            "materials are invented and for demonstration only."
        ),
        "alerts.title": "Alerts",
        "alerts.caption": (
            "Every material with its key figures, most urgent first. "
            "Click a column header to sort, select a row for details."
        ),
        "alerts.filter.status": "Status",
        "alerts.filter.all": "All",
        "alerts.filter.search": "Search",
        "alerts.filter.search_hint": "Material number or description",
        "alerts.count": "{shown} of {total} materials",
        "alerts.open_detail": "Open details: {material}",
        "alerts.select_hint": "Select a row to open the material detail.",
        "alerts.download": "Excel export",
        "alerts.download_file": "alerts_{date}.xlsx",
        "detail.title": "Material detail",
        "detail.select": "Material",
        "detail.series.receipts": "Goods receipt",
        "detail.series.stock": "Stock",
        "detail.series.missing": "Missing day (estimated)",
        "detail.series.consumption": "Derived consumption",
        "detail.series.projection": "Projection without further receipts",
        "detail.series.band": "Variability band (± 1 σ)",
        "detail.chart.title": "Stock history {material} · plant {plant}",
        "detail.chart.x": "Date",
        "detail.chart.y_stock": "Stock ({unit})",
        "detail.chart.y_consumption": "Consumption ({unit}/day)",
        "detail.chart.caption": (
            "Dashed: projection if no further receipt arrives – not a demand forecast. "
            "Crosses mark days without a complete stock snapshot."
        ),
        "detail.fact.avg_demand": "Avg. consumption per day",
        "detail.fact.sigma_weekly": "Variability per week (σ)",
        "detail.fact.classes": "ABC / XYZ",
        "detail.fact.last_consumption": "Last consumption",
        "detail.fact.dq_score": "Data quality",
        "detail.facts.title": "Key figures",
        "detail.master.title": "Master data",
        "detail.master.price": "Price per unit",
        "detail.master.lead_time": "Lead time",
        "detail.master.min_stock": "Minimum stock (master)",
        "detail.master.max_stock": "Maximum stock (master)",
        "detail.master.safety_calc": "Safety stock (calculated)",
        "detail.master.deviation": "Deviation master vs. calculated",
        "detail.days": "{days} days",
        "detail.anomaly": "Anomaly: unusual demand or goods receipt recently.",
        "detail.sloc.toggle": "Split by storage location",
        "detail.sloc.name": "Storage location {sloc}",
        "detail.sloc.title": "Stock per storage location",
        "overview.title": "Shortages and overstock at a glance",
        "overview.subtitle": "Automatic assessment of every material as of {date}",
        "overview.kpi.critical": "Shortages (critical)",
        "overview.kpi.critical_help": "Stock below safety stock or zero.",
        "overview.kpi.warning": "Below reorder point",
        "overview.kpi.warning_help": "Stock below the reorder point: check that an order is open.",
        "overview.kpi.overstock": "Overstock",
        "overview.kpi.overstock_help": "Stock above the maximum stock or the target coverage.",
        "overview.kpi.dead_stock": "Dead stock",
        "overview.kpi.dead_stock_help": "Stock on hand, but no consumption for a long time.",
        "overview.kpi.stock_value": "Stock value",
        "overview.kpi.stock_value_help": "Sum of stock × price over all materials.",
        "overview.kpi.excess_value": "Capital tied up in excess",
        "overview.kpi.excess_value_help": (
            "Value above the maximum stock plus the whole stock value of dead stock."
        ),
        "overview.kpi.critical_proof": "Stock < safety stock",
        "overview.kpi.warning_proof": "Order open?",
        "overview.kpi.overstock_proof": "Stock > maximum",
        "overview.kpi.dead_stock_proof": "≥ {days} days without use",
        "overview.kpi.stock_value_proof": "{count} materials",
        "overview.kpi.excess_value_proof": "Overstock + dead stock",
        "overview.plant_tag": "Plant {plant}",
        "overview.status_chart.title": "Materials by status",
        "overview.status_chart.x": "Number of materials",
        "overview.status_chart.hover": "%{y}: %{x} materials",
        "overview.value_chart.title": "Stock value over time",
        "overview.value_chart.x": "Date",
        "overview.value_chart.y": "Stock value (EUR)",
        "overview.value_chart.hover": "%{{x|{date_format}}}: €%{{y:,.0f}}",
        "overview.top.title": "The 10 most urgent materials",
        "overview.top.caption": "Sorted by status, then by value at risk; class A shortages first.",
    },
}


def _build(lang: str) -> dict[str, str]:
    strings = dict(_TEXT[lang])
    strings |= {f"status.{code}": label for code, label in STATUS_LABELS[lang].items()}
    strings |= {f"col.{name}": label for name, label in COLUMN_LABELS[lang].items()}
    strings |= {f"threshold.{name}": label for name, label in THRESHOLD_LABELS[lang].items()}
    return strings


STRINGS: dict[str, dict[str, str]] = {lang: _build(lang) for lang in state.LANGUAGES}


def translate(key: str, lang: str, **values: object) -> str:
    """The string for `key` in `lang`, with `{placeholders}` filled from `values`."""
    text = STRINGS[lang].get(key)
    if text is None:
        if os.environ.get(STRICT_ENV):
            raise KeyError(f"Missing translation key {key!r} for language {lang!r}")
        return key
    return text.format(**values) if values else text


def t(key: str, **values: object) -> str:
    """The string for `key` in the current language."""
    return translate(key, state.lang(), **values)


# --- Number and date formatting ------------------------------------------------------------


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value)) or value is pd.NaT


def fmt_number(value: float | None, decimals: int = 0, lang: str | None = None) -> str:
    """1,234.5 in English, 1.234,5 in German; a dash when missing."""
    if _is_missing(value):
        return MISSING
    text = f"{value:,.{decimals}f}"
    if (lang or state.lang()) == "de":
        text = text.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return text


def fmt_eur(value: float | None, lang: str | None = None) -> str:
    """Whole euros: 1.234 € in German, €1,234 in English."""
    if _is_missing(value):
        return MISSING
    number = fmt_number(value, 0, lang)
    return f"{number} €" if (lang or state.lang()) == "de" else f"€{number}"


def fmt_eur_compact(value: float | None, lang: str | None = None) -> str:
    """Large amounts shortened: 8,2 Mio. € / €8.2M, 820 Tsd. € / €820K."""
    if _is_missing(value):
        return MISSING
    german = (lang or state.lang()) == "de"
    for size, de_unit, en_unit in ((1e6, "Mio.", "M"), (1e3, "Tsd.", "K")):
        if abs(value) >= size:
            number = fmt_number(value / size, 1, lang)
            return f"{number} {de_unit} €" if german else f"€{number}{en_unit}"
    return fmt_eur(value, lang)


def fmt_pct(share: float | None, decimals: int = 0, lang: str | None = None) -> str:
    """A share as a percentage: 12 % in German, 12% in English."""
    if _is_missing(share):
        return MISSING
    number = fmt_number(share * 100, decimals, lang)
    return f"{number} %" if (lang or state.lang()) == "de" else f"{number}%"


def fmt_coverage(days: float | None, lang: str | None = None) -> str:
    """Days of coverage; unlimited coverage (no demand) shows as "> 365"."""
    if _is_missing(days):
        return MISSING
    if math.isinf(days):
        return UNLIMITED_COVERAGE
    return fmt_number(days, 0, lang)


def fmt_date(value: object, lang: str | None = None) -> str:
    """31.10.2026 in German, 2026-10-31 in English."""
    if _is_missing(value) or pd.isna(value):
        return MISSING
    stamp = pd.Timestamp(value)
    return stamp.strftime("%d.%m.%Y" if (lang or state.lang()) == "de" else "%Y-%m-%d")


def date_format(lang: str | None = None) -> str:
    """Date format for widgets and Plotly axes."""
    return "DD.MM.YYYY" if (lang or state.lang()) == "de" else "YYYY-MM-DD"


def plotly_date_format(lang: str | None = None) -> str:
    return "%d.%m.%Y" if (lang or state.lang()) == "de" else "%Y-%m-%d"


def plotly_separators(lang: str | None = None) -> str:
    """Plotly's `separators`: decimal mark first, then the thousands separator."""
    return ",." if (lang or state.lang()) == "de" else ".,"


def status_label(code: str) -> str:
    return t(f"status.{code}")
