import sqlite3
from datetime import datetime, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QScrollArea, QGridLayout, QSizePolicy, QPushButton
)

from database import get_conn
from app_utils import format_eur

class DashboardPage(QWidget):
    def __init__(self, user_id: int, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        
        # Colori della palette per la UI
        self.colors = {
            "danger": "#dc3545",   # Rosso
            "warning": "#ffc107",  # Giallo/Arancio
            "info": "#17a2b8",     # Azzurro
            "success": "#28a745",  # Verde
            "text_dark": "#2c3e50",
            "text_muted": "#7f8c8d",
            "bg_card": "#ffffff",
            "bg_page": "#f4f6f9"
        }
        
        self._build_ui()
        self.aggiorna_dati()

    def showEvent(self, event):
        """Scatta automaticamente ogni volta che la pagina diventa visibile"""
        super().showEvent(event)
        self.aggiorna_dati()

    def _build_ui(self):
        # Imposta lo sfondo della pagina intera (grigio chiarissimo per far risaltare le card bianche)
        self.setStyleSheet(f"background-color: {self.colors['bg_page']};")
        
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        inner_widget = QWidget()
        self.main_layout = QVBoxLayout(inner_widget)
        self.main_layout.setContentsMargins(24, 24, 24, 24)
        self.main_layout.setSpacing(24)

        # --- INTESTAZIONE ---
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)
        titolo = QLabel("Dashboard Aziendale")
        titolo.setStyleSheet(f"font-size: 28px; font-weight: 800; color: {self.colors['text_dark']};")
        sottotitolo = QLabel("Panoramica aggiornata in tempo reale sulle scadenze e le operazioni.")
        sottotitolo.setStyleSheet(f"font-size: 15px; color: {self.colors['text_muted']};")
        header_layout.addWidget(titolo)
        header_layout.addWidget(sottotitolo)
        self.main_layout.addLayout(header_layout)

        # --- SEZIONE 1: KPI CARDS (Riga superiore) ---
        self.kpi_layout = QHBoxLayout()
        self.kpi_layout.setSpacing(20)
        self.main_layout.addLayout(self.kpi_layout)

        # --- SEZIONE 2: LISTE DETTAGLIATE (Affiancate) ---
        self.lists_layout = QHBoxLayout()
        self.lists_layout.setSpacing(20)
        
        # Colonna Sinistra (Fatture)
        self.col_sx_layout = QVBoxLayout()
        lbl_fatture = QLabel("🗓️ Scadenze Finanziarie (Prossimi 30gg)")
        lbl_fatture.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {self.colors['text_dark']}; margin-bottom: 10px;")
        self.col_sx_layout.addWidget(lbl_fatture)
        self.layout_lista_fatture = QVBoxLayout()
        self.layout_lista_fatture.setSpacing(10)
        self.col_sx_layout.addLayout(self.layout_lista_fatture)
        self.col_sx_layout.addStretch(1)
        
        # Colonna Destra (Macchinari)
        self.col_dx_layout = QVBoxLayout()
        lbl_macchinari = QLabel("🚜 Avvisi Manutenzione Mezzi")
        lbl_macchinari.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {self.colors['text_dark']}; margin-bottom: 10px;")
        self.col_dx_layout.addWidget(lbl_macchinari)
        self.layout_lista_macchinari = QVBoxLayout()
        self.layout_lista_macchinari.setSpacing(10)
        self.col_dx_layout.addLayout(self.layout_lista_macchinari)
        self.col_dx_layout.addStretch(1)

        self.lists_layout.addLayout(self.col_sx_layout, 1) # Il peso '1' fa sì che si dividano lo spazio a metà
        self.lists_layout.addLayout(self.col_dx_layout, 1)
        
        self.main_layout.addLayout(self.lists_layout)
        self.main_layout.addStretch(1)

        scroll_area.setWidget(inner_widget)
        outer_layout.addWidget(scroll_area)

    # --- COMPONENTI GRAFICI REUSABILI ---

    def _crea_kpi_card(self, titolo, valore, sotto_testo, colore_accento):
        """Crea un riquadro riassuntivo elegante per la cima della pagina."""
        card = QFrame()
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {self.colors['bg_card']};
                border-radius: 10px;
                border: 1px solid #e1e8ed;
                border-bottom: 4px solid {colore_accento};
            }}
        """)
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(8)
        
        lbl_titolo = QLabel(titolo.upper())
        lbl_titolo.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {self.colors['text_muted']}; border: none;")
        
        lbl_valore = QLabel(valore)
        lbl_valore.setStyleSheet(f"font-size: 26px; font-weight: 800; color: {self.colors['text_dark']}; border: none;")
        
        lbl_sotto = QLabel(sotto_testo)
        lbl_sotto.setStyleSheet(f"font-size: 12px; color: {self.colors['text_muted']}; border: none;")
        
        layout.addWidget(lbl_titolo)
        layout.addWidget(lbl_valore)
        layout.addWidget(lbl_sotto)
        
        return card

    def _crea_list_item(self, titolo, dettaglio, colore_accento, icona="📄", movimento_id=None):
        """Crea una riga pulita per le liste delle scadenze, con bottone rapido se necessario."""
        item = QFrame()
        item.setStyleSheet(f"""
            QFrame {{
                background-color: {self.colors['bg_card']};
                border-radius: 8px;
                border: 1px solid #e1e8ed;
                border-left: 5px solid {colore_accento};
            }}
        """)
        
        layout = QHBoxLayout(item)
        layout.setContentsMargins(15, 12, 15, 12)
        layout.setSpacing(15)
        
        lbl_icona = QLabel(icona)
        lbl_icona.setStyleSheet("font-size: 20px; border: none; background: transparent;")
        lbl_icona.setFixedWidth(30)
        layout.addWidget(lbl_icona)
        
        testo_layout = QVBoxLayout()
        testo_layout.setSpacing(4)
        
        lbl_titolo = QLabel(titolo)
        lbl_titolo.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {self.colors['text_dark']}; border: none; background: transparent;")
        lbl_titolo.setWordWrap(True)
        
        lbl_dettaglio = QLabel(dettaglio)
        lbl_dettaglio.setStyleSheet(f"font-size: 13px; color: {self.colors['text_muted']}; border: none; background: transparent;")
        lbl_dettaglio.setWordWrap(True)
        
        testo_layout.addWidget(lbl_titolo)
        testo_layout.addWidget(lbl_dettaglio)
        layout.addLayout(testo_layout, 1)
        
        # --- NUOVO: BOTTONE PAGAMENTO RAPIDO ---
        if movimento_id is not None:
            btn_pagato = QPushButton("✔️ Saldato")
            btn_pagato.setCursor(Qt.PointingHandCursor)
            btn_pagato.setStyleSheet(f"""
                QPushButton {{
                    background-color: {self.colors['success']};
                    color: white;
                    border-radius: 5px;
                    padding: 6px 12px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: #218838;
                }}
            """)
            # Colleghiamo il pulsante alla funzione di salvataggio passando l'ID specifico
            btn_pagato.clicked.connect(lambda _, mid=movimento_id: self.segna_come_pagato(mid))
            layout.addWidget(btn_pagato)
            
        return item
    

    # --- LOGICA DATI ---

    def _clear_layout(self, layout):
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _parse_date(self, date_str):
        if not date_str: return None
        date_str = str(date_str).strip()
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                pass
        return None

    def segna_come_pagato(self, movimento_id):
        """Aggiorna lo stato della fattura e rinfresca la dashboard"""
        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute("UPDATE movimenti SET stato_pagamento='PAGATO' WHERE id=?", (movimento_id,))
            self.aggiorna_dati()
        except Exception as exc:
            pass

    def aggiorna_dati(self):
        self._clear_layout(self.kpi_layout)
        self._clear_layout(self.layout_lista_fatture)
        self._clear_layout(self.layout_lista_macchinari)
        
        oggi = datetime.now().date()
        
        # 1. Elaborazione Fatture
        scadenze_fatture = []
        totale_importo_scadenza = 0.0
        fatture_scadute_count = 0
        
        # 1. Elaborazione Fatture
        scadenze_fatture = []
        totale_importo_scadenza = 0.0
        fatture_scadute_count = 0
        
        try:
            with get_conn() as conn:
                c = conn.cursor()
                # Aggiunto "id" e il COALESCE che avevamo corretto prima!
                c.execute('''
                    SELECT id, descrizione, importo, COALESCE(NULLIF(TRIM(parser_due_date), ''), data_op) as data_riferimento
                    FROM movimenti 
                    WHERE user_id=? AND tipo='USCITA' AND stato_pagamento='DA PAGARE'
                ''', (self.user_id,))
                
                for mov_id, desc, importo, data_str in c.fetchall():
                    data_scadenza = self._parse_date(data_str)
                    if data_scadenza:
                        giorni_rimanenti = (data_scadenza - oggi).days
                        if giorni_rimanenti <= 30:
                            # Salviamo anche mov_id nella tupla
                            scadenze_fatture.append((mov_id, desc, importo, data_scadenza, giorni_rimanenti))
                            totale_importo_scadenza += float(importo or 0)
                            if giorni_rimanenti < 0:
                                fatture_scadute_count += 1
        except Exception:
            pass

        scadenze_fatture.sort(key=lambda x: x[3])
        
        # 2. Elaborazione Macchinari
        allarmi_macchinari = []
        try:
            with get_conn() as conn:
                c = conn.cursor()
                c.execute('''
                    SELECT m.nome, MAX(mm.data_manutenzione)
                    FROM macchinari m
                    LEFT JOIN manutenzioni_macchinari mm ON m.id = mm.macchinario_id
                    WHERE m.user_id=?
                    GROUP BY m.id, m.nome
                ''', (self.user_id,))
                
                for nome, data_str in c.fetchall():
                    if not data_str:
                        allarmi_macchinari.append((nome, None, True, 0))
                    else:
                        data_manutenzione = self._parse_date(data_str)
                        if data_manutenzione:
                            giorni_passati = (oggi - data_manutenzione).days
                            if giorni_passati >= 365:
                                allarmi_macchinari.append((nome, data_manutenzione, False, giorni_passati))
        except Exception:
            pass
            
        allarmi_macchinari.sort(key=lambda x: x[3], reverse=True)

        # --- POPOLAMENTO KPI CARDS ---
        colore_kpi_fat = self.colors['danger'] if fatture_scadute_count > 0 else self.colors['warning']
        self.kpi_layout.addWidget(self._crea_kpi_card(
            "Uscite a breve termine (30gg)", 
            format_eur(totale_importo_scadenza), 
            f"{len(scadenze_fatture)} documenti di cui {fatture_scadute_count} già scaduti" if fatture_scadute_count > 0 else f"{len(scadenze_fatture)} documenti in arrivo",
            colore_kpi_fat
        ))
        
        colore_kpi_mezzi = self.colors['danger'] if len(allarmi_macchinari) > 0 else self.colors['success']
        self.kpi_layout.addWidget(self._crea_kpi_card(
            "Stato Parco Mezzi", 
            f"{len(allarmi_macchinari)} Avvisi" if allarmi_macchinari else "OK", 
            "Mezzi che necessitano di revisione/tagliando" if allarmi_macchinari else "Tutti i macchinari sono in regola",
            colore_kpi_mezzi
        ))
        
        # --- POPOLAMENTO LISTE ---
        
        # Lista Fatture
        if not scadenze_fatture:
            self.layout_lista_fatture.addWidget(self._crea_list_item("Tutto regolare", "Nessuna fattura in scadenza nel breve periodo.", self.colors['success'], "✅"))
        else:
            for mov_id, desc, importo, data_scadenza, giorni in scadenze_fatture:
                data_fmt = data_scadenza.strftime('%d/%m/%Y')
                if giorni < 0:
                    col, sub = self.colors['danger'], f"Scaduta da {abs(giorni)} giorni ({data_fmt}) - {format_eur(importo)}"
                elif giorni <= 7:
                    col, sub = self.colors['warning'], f"Scade tra {giorni} giorni ({data_fmt}) - {format_eur(importo)}"
                else:
                    col, sub = self.colors['info'], f"Scade il {data_fmt} - {format_eur(importo)}"
                
                # Passiamo il movimento_id al widget
                self.layout_lista_fatture.addWidget(self._crea_list_item(desc, sub, col, "💸", movimento_id=mov_id))
                
        # Lista Macchinari
        if not allarmi_macchinari:
            self.layout_lista_macchinari.addWidget(self._crea_list_item("Nessun intervento richiesto", "Nessun allarme manutenzione registrato.", self.colors['success'], "✅"))
        else:
            for nome, data_man, mai_fatta, giorni_passati in allarmi_macchinari:
                if mai_fatta:
                    col, sub = self.colors['danger'], "Non è mai stato registrato alcun intervento."
                else:
                    col, sub = self.colors['warning'], f"Ultimo intervento: {data_man.strftime('%d/%m/%Y')} ({giorni_passati} giorni fa)."
                
                self.layout_lista_macchinari.addWidget(self._crea_list_item(nome, sub, col, "🔧"))