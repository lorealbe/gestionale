
import os
import re
import json
import fitz  # PyMuPDF

# ==========================================
# 1. IL MOTORE DETERMINISTICO (Geometria Dinamica)
# ==========================================
class RegexInvoiceParser:
    def processa_fattura(self, file_path, progress_callback=None):
        if not os.path.exists(file_path):
            raise FileNotFoundError("File non trovato.")

        if progress_callback: progress_callback("Estrazione testo dal PDF...")
        testo_estratto = self._estrai_testo_pdf(file_path)
        
        if not testo_estratto.strip():
            raise ValueError("Il PDF non contiene testo digitale. Sembra essere un'immagine o una scansione.")

        if progress_callback: progress_callback("Analisi logica (Regex) in corso...")
        risultato = self._estrai_dati_regex(testo_estratto)

        if progress_callback: progress_callback("Ricerca posizionale Fornitore (Alto a SX)...")
        risultato["supplier_name"] = self._estrai_fornitore_posizionale(file_path)

        if progress_callback: progress_callback("Ricerca Totali (Ultima pagina, Basso a DX)...")
        totali = self._estrai_totali_mirati(file_path, testo_estratto)
        risultato.update(totali)

        if progress_callback: progress_callback("Estrazione ed elaborazione lista prodotti...")
        risultato["line_items"] = self._estrai_righe_prodotti(file_path)

        return risultato

    def _estrai_testo_pdf(self, file_path):
        """Estrae il testo dal PDF nativo."""
        testo = ""
        try:
            documento = fitz.open(file_path)
            for pagina in documento:
                testo += pagina.get_text("text") + "\n"
            documento.close()
        except Exception as e:
            raise RuntimeError(f"Errore lettura PDF: {e}")
        return testo

    def _estrai_fornitore_posizionale(self, file_path):
        """Estrae il nome del fornitore (Alto a SX, Pagina 1)."""
        try:
            documento = fitz.open(file_path)
            pagina = documento[0] 
            blocchi = pagina.get_text("blocks") 
            documento.close()
            
            blocchi_testo = [b for b in blocchi if b[6] == 0 and b[4].strip()]
            if not blocchi_testo: return ""
                
            blocchi_testo.sort(key=lambda b: (round(b[1] / 10), b[0]))
            testo_primo_blocco = blocchi_testo[0][4].strip()
            nome_fornitore = testo_primo_blocco.split('\n')[0].strip()
            
            return nome_fornitore
        except Exception as e:
            return ""

    @staticmethod
    def _normalizza_numero_token(token):
        testo = str(token or "").strip()
        testo = testo.replace("\u00a0", "").replace(" ", "")
        testo = testo.replace("€", "").replace("EUR", "").replace("eur", "")
        testo = testo.replace("'", "").replace("’", "")
        testo = testo.strip("()[]{}:;")
        testo = re.sub(r'^[^\d\-]+', '', testo)
        testo = re.sub(r'[^\d.,\-%]+$', '', testo)
        return testo

    @staticmethod
    def _numero_like(token, allow_percent=False):
        testo = str(token or "").strip()
        if not testo:
            return False
        if allow_percent and testo.endswith("%"):
            testo = testo[:-1]
        elif "%" in testo:
            return False
        return bool(re.match(r'^-?(?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,]\d{1,4})?$', testo))

    @staticmethod
    def _parse_float_locale(raw):
        testo = re.sub(r'[^\d.,\-]', '', str(raw or ""))
        if not testo:
            return 0.0
        if ',' in testo and '.' in testo:
            if testo.rfind(',') > testo.rfind('.'):
                testo = testo.replace('.', '').replace(',', '.')
            else:
                testo = testo.replace(',', '')
        elif ',' in testo:
            testo = testo.replace(',', '.')
        try:
            return float(testo)
        except Exception:
            return 0.0

    def _estrai_righe_prodotti(self, file_path):
        """Ricostruisce la tabella creando Intervalli X dinamici per ogni colonna."""
        line_items = []

        def normalizza_label(label):
            testo = str(label or "").lower()
            sostituzioni = {
                "à": "a", "á": "a", "è": "e", "é": "e", "ì": "i", "ò": "o", "ó": "o", "ù": "u",
            }
            for src, dst in sostituzioni.items():
                testo = testo.replace(src, dst)
            return re.sub(r'[^a-z0-9%]', '', testo)

        try:
            documento = fitz.open(file_path)
            try:
                in_tabella = False
                buffer_descrizione = ""
                ultimo_rigo_era_valido = False
                col_coords = {}

                # Parole chiave di uscita (fine tabella) OTTIMIZZATE
                # Parole chiave di uscita (fine tabella) - Togliamo i totali da qui!
                stop_words = r'(?i)\b(?:scadenza|pagamento|banca|iban|esigibilit[aà]|condizioni\s+generali|non\s+si\s+accettano|pagamenti\s+dovranno|merce\s+di\s+ritorno|reclami|difettos[ao]|arrotondamenti|non\s+conforme)\b'
                
                # Metadati e Totali da SALTARE (la tabella rimane attiva per le righe successive)
                ignore_patterns = r'(?i)^(?:tipo\s+dato|valore\s+testo|valore\s+data|cig\b|cup\b|riferimento\b)|\b(?:totale\s+documento|totale\s+da\s+pagare|totale\s+imponibile|totale\s+iva|riepilogo|imponibile|imposta)\b'
                # Metadati da saltare
                ignore_patterns = r'(?i)^(?:tipo\s+dato|valore\s+testo|valore\s+data|cig\b|cup\b|riferimento\b)'

                qta_labels = {"qta", "qt", "quantita", "qty"}
                prezzo_labels = {"prezzo", "unitario", "prezzounitario", "unitprice", "importounitario", "prezzoivato"}
                totale_labels = {"importo", "totale", "ammontare", "valore", "netto"}
                iva_labels = {"iva", "%iva", "aliquotaiva", "vat", "perciva"}
                desc_labels = {"descrizione", "codice", "articolo", "articoli", "prodotto", "prodotti", "causale", "bene", "servizio", "dettaglio"}
                pattern_iva_um = r'^(?:N[1-9](?:\.\d)?|E\d+|esente|art.*|%\s*\d+|\d+\s*%|PZ|KG|TN|LT|NR|M2|M3|M|Q|Q\.LI|L|CP|CAD.*|CT)$'
                address_like_pattern = r'(?i)\b(?:via|viale|piazza|loc\.?|frazione|cap\b|italia|\([a-z]{2}\))\b'

                for num_pag in range(len(documento)):
                    pagina = documento[num_pag]
                    words = pagina.get_text("words")

                    # Reset di sicurezza al cambio pagina per evitare "sanguinamento" descrittivo
                    ultimo_rigo_era_valido = False
                    buffer_descrizione = ""

                    righe_y = {}
                    for w in words:
                        y_centro = round((w[1] + w[3]) / 2 / 4) * 4
                        if y_centro not in righe_y:
                            righe_y[y_centro] = []
                        righe_y[y_centro].append(w)

                    y_ordinate = sorted(righe_y.keys())

                    for y in y_ordinate:
                        parole_riga = righe_y[y]
                        parole_riga.sort(key=lambda w: w[0])
                        testo_pulito = " ".join([str(w[4]) for w in parole_riga]).strip()

                        if not testo_pulito:
                            continue

                        # === FASE 1: DEFINIZIONE GEOMETRICA DELLE COLONNE ===
                        if not in_tabella:
                            temp_centers = {}
                            labels_riga = []

                            for w in parole_riga:
                                testo_label = normalizza_label(w[4])
                                if not testo_label:
                                    continue
                                labels_riga.append(testo_label)
                                x_center = (w[0] + w[2]) / 2

                                if testo_label in qta_labels:
                                    temp_centers['qta'] = x_center
                                elif testo_label in prezzo_labels:
                                    temp_centers['prezzo'] = x_center
                                elif testo_label in totale_labels:
                                    temp_centers['totale'] = x_center
                                elif testo_label in iva_labels:
                                    temp_centers['iva'] = x_center

                            has_desc = any(lbl in desc_labels for lbl in labels_riga) or bool(
                                re.search(r'(?i)\b(?:descrizione|codice|articolo|prodotto|causale|bene|servizio)\b', testo_pulito)
                            )

                            if len(temp_centers) >= 2 and (has_desc or len(temp_centers) >= 3):
                                in_tabella = True
                                col_coords.clear()
                                sorted_cols = sorted(temp_centers.items(), key=lambda item: item[1])

                                for i in range(len(sorted_cols)):
                                    nome_col = sorted_cols[i][0]
                                    x_attuale = sorted_cols[i][1]
                                    min_x = x_attuale - 90 if i == 0 else (sorted_cols[i - 1][1] + x_attuale) / 2
                                    max_x = x_attuale + 180 if i == len(sorted_cols) - 1 else (x_attuale + sorted_cols[i + 1][1]) / 2
                                    col_coords[nome_col] = (min_x, max_x)

                                buffer_descrizione = ""
                            continue

                        # === FASE 2: USCITA O FILTRO ===
                        if re.search(stop_words, testo_pulito):
                            in_tabella = False
                        if re.search(stop_words, testo_pulito):
                            in_tabella = False
                            ultimo_rigo_era_valido = False
                            continue

                        if re.search(ignore_patterns, testo_pulito):
                            continue

                        # Salta intestazioni ripetute
                        if re.search(r'(?i)\b(?:descrizione|codice|articolo|prodotto)\b', testo_pulito) and re.search(r'(?i)\b(?:prezzo|totale|importo|q\.?t[aà]|quantit[aà])\b', testo_pulito):
                            continue

                        # === FASE 3: ASSEGNAZIONE GEOMETRICA ===
                        item = {"description": "", "quantity": "1", "price": "0.00", "line_total": "0.00", "vat": ""}
                        desc_words = []
                        numeri_non_assegnati = []
                        ha_importi_valori = False

                        for w in parole_riga:
                            testo_parola = str(w[4]).strip()
                            x_center = (w[0] + w[2]) / 2
                            token_num = self._normalizza_numero_token(testo_parola)
                            is_num = self._numero_like(token_num)
                            is_num_pct = self._numero_like(token_num, allow_percent=True)

                            colonna_assegnata = None
                            for nome_col, (min_x, max_x) in col_coords.items():
                                if min_x <= x_center <= max_x:
                                    colonna_assegnata = nome_col
                                    break

                            if colonna_assegnata:
                                if colonna_assegnata == 'iva' and is_num_pct:
                                    item['vat'] = token_num
                                    continue

                                if is_num:
                                    if colonna_assegnata == 'prezzo':
                                        item['price'] = token_num
                                        ha_importi_valori = True
                                    elif colonna_assegnata == 'totale':
                                        item['line_total'] = token_num
                                        ha_importi_valori = True
                                    elif colonna_assegnata == 'qta':
                                        item['quantity'] = token_num
                                    else:
                                        numeri_non_assegnati.append(token_num)
                                    continue

                            if is_num:
                                numeri_non_assegnati.append(token_num)
                            elif not re.match(pattern_iva_um, testo_parola, re.IGNORECASE):
                                desc_words.append(testo_parola)

                        numeri_positivi = [n for n in numeri_non_assegnati if self._parse_float_locale(n) > 0.0]

                        if self._parse_float_locale(item["price"]) <= 0.0 and self._parse_float_locale(item["line_total"]) <= 0.0 and len(numeri_positivi) >= 2:
                            if self._parse_float_locale(item["quantity"]) <= 0.0:
                                item["quantity"] = numeri_positivi[0]
                            item["price"] = numeri_positivi[-2]
                            item["line_total"] = numeri_positivi[-1]
                            ha_importi_valori = True

                        if self._parse_float_locale(item["price"]) <= 0.0 and self._parse_float_locale(item["line_total"]) > 0.0:
                            item["price"] = item["line_total"]

                        desc_inline = " ".join(desc_words).strip()

                        if ha_importi_valori or self._parse_float_locale(item["line_total"]) > 0.0:
                            # Scarta solo le righe realmente non economiche (zero totale e zero prezzo)
                            if self._parse_float_locale(item["price"]) == 0.0 and self._parse_float_locale(item["line_total"]) == 0.0:
                                ultimo_rigo_era_valido = False
                                continue

                            buffer_use = buffer_descrizione
                            if buffer_use and re.search(address_like_pattern, buffer_use):
                                buffer_use = ""

                            item["description"] = (buffer_use + " " + desc_inline).strip() or "-"
                            buffer_descrizione = ""
                            line_items.append(item)
                            ultimo_rigo_era_valido = True
                        else:
                            if desc_inline:
                                # FIX: Evita di concatenare se la riga orfana è troppo lunga 
                                # o sembra iniziare un nuovo prodotto (es. inizia con un codice o lettere maiuscole)
                                sembra_nuovo_prodotto = bool(re.match(r'^[A-Z0-9]{3,}', desc_inline))
                                
                                if len(line_items) > 0 and ultimo_rigo_era_valido and not sembra_nuovo_prodotto:
                                    line_items[-1]["description"] = (line_items[-1]["description"] + " " + desc_inline).strip()
                                else:
                                    buffer_descrizione = (buffer_descrizione + " " + desc_inline).strip()
                                    ultimo_rigo_era_valido = False # Forza il reset
            finally:
                documento.close()

            if not line_items:
                line_items = self._estrai_righe_prodotti_fallback(file_path, stop_words, ignore_patterns)

        except Exception as e:
            print(f"Errore estrazione prodotti: {e}")
        return line_items

    def _estrai_righe_prodotti_fallback(self, file_path, stop_words, ignore_patterns):
        """Fallback testuale quando la tabella non viene agganciata geometricamente."""
        line_items = []
        try:
            documento = fitz.open(file_path)
            try:
                in_tabella = False
                buffer_descrizione = ""
                header_pattern = r'(?i)\b(?:descrizione|codice|articol[oi]|prodott[oi]|causale|bene|servizio)\b'
                value_pattern = r'(?i)\b(?:q\.?t[aà]|quantit[aà]|prezzo|importo|totale|iva)\b'
                hard_excluded = r'(?i)\b(?:fattura|documento|cliente|fornitore|cedente|cessionario|indirizzo|banca|iban|scadenza|pagamento|imponibile|totale\s+documento|totale\s+da\s+pagare)\b'
                pattern_iva_um = r'^(?:N[1-9](?:\.\d)?|E\d+|esente|art.*|%\s*\d+|\d+\s*%|PZ|KG|TN|LT|NR|M2|M3|M|Q|Q\.LI|L|CP|CAD.*|CT)$'
                address_like_pattern = r'(?i)\b(?:via|viale|piazza|loc\.?|frazione|cap\b|italia|\([a-z]{2}\))\b'

                for pagina in documento:
                    for raw_line in pagina.get_text("text").splitlines():
                        testo_pulito = " ".join(str(raw_line).split()).strip()
                        if not testo_pulito:
                            continue

                        is_header = bool(re.search(header_pattern, testo_pulito) and re.search(value_pattern, testo_pulito))
                        if is_header:
                            in_tabella = True
                            continue

                        if re.search(stop_words, testo_pulito):
                            in_tabella = False
                            continue

                        if re.search(ignore_patterns, testo_pulito):
                            continue

                        # In modalita permissiva (senza header intercettata), evita righe anagrafiche.
                        if not in_tabella and re.search(hard_excluded, testo_pulito):
                            continue

                        parts = testo_pulito.split()
                        numeri = []
                        iva = ""
                        desc_words = []

                        for token in parts:
                            token_num = self._normalizza_numero_token(token)
                            if self._numero_like(token_num, allow_percent=True):
                                if token_num.endswith("%") and not iva:
                                    iva = token_num
                                else:
                                    numeri.append(token_num)
                            elif not re.match(pattern_iva_um, token, re.IGNORECASE):
                                desc_words.append(token)

                        numeri_positivi = [n for n in numeri if self._parse_float_locale(n) > 0.0]
                        has_decimal = any(re.search(r'[.,]\d{2,4}$', n.rstrip('%')) for n in numeri_positivi)
                        descrizione_inline = " ".join(desc_words).strip()

                        if len(numeri_positivi) >= 2 and has_decimal and descrizione_inline:
                            quantity = numeri_positivi[0]
                            price = numeri_positivi[-2]
                            line_total = numeri_positivi[-1]

                            if self._parse_float_locale(quantity) <= 0.0:
                                quantity = "1"
                            if self._parse_float_locale(quantity) > 10000 and len(numeri_positivi) >= 3:
                                quantity = numeri_positivi[-3]

                            buffer_use = buffer_descrizione
                            if buffer_use and re.search(address_like_pattern, buffer_use):
                                buffer_use = ""

                            descrizione = (buffer_use + " " + descrizione_inline).strip()
                            buffer_descrizione = ""

                            line_items.append({
                                "description": descrizione or "-",
                                "quantity": quantity,
                                "price": price,
                                "line_total": line_total,
                                "vat": iva,
                            })
                        elif descrizione_inline and in_tabella:
                            buffer_descrizione = (buffer_descrizione + " " + descrizione_inline).strip()
            finally:
                documento.close()
        except Exception:
            return line_items
        return line_items

    def _estrai_totali_mirati(self, file_path, testo_intero):
        """Ricerca totali (Bottom-Right, Ultima pagina -> Retro)."""
        dati_totali = {"total_amount": "", "taxable_total": "", "vat_total": ""}
        try:
            documento = fitz.open(file_path)
            num_pagine = len(documento)
            def trova_importo(keywords, liste_testi):
                for kw in keywords:
                    for testo_target in liste_testi:
                        pattern = r'(?i)(?:' + kw + r')(?:[\s:]*\d{1,2}[\s]*%)?[^\d]{0,60}?((?:\d{1,3}(?:[.,\s]\d{3})+|\d+)[.,]\d{2})\b'
                        match = re.search(pattern, testo_target)
                        if match: return match.group(1).replace(' ', '')
                return ""
            kw_tot = [r'totale documento', r'totale da pagare', r'totale fattura', r'totale(?!\s+riga)']
            kw_imp = [r'totale imponibile', r'imponibile']
            kw_iva = [r'totale iva', r'totale imposta', r'iva\s*€', r'iva\s*:']
            for i in range(num_pagine - 1, -1, -1):
                pagina = documento[i]
                testo_clip = pagina.get_text("text", clip=fitz.Rect(pagina.rect.width*0.4, pagina.rect.height*0.5, pagina.rect.width, pagina.rect.height)).replace('\n', ' ')
                testi = [testo_clip, pagina.get_text("text").replace('\n', ' ')]
                tot_f = trova_importo(kw_tot, testi)
                if tot_f:
                    dati_totali = {"total_amount": tot_f, "taxable_total": trova_importo(kw_imp, testi), "vat_total": trova_importo(kw_iva, testi)}
                    break
            documento.close()
            return dati_totali
        except: return dati_totali

    @staticmethod
    def _standardizza_data(data_str):
        """Converte date testuali o ISO in un formato DD/MM/YYYY standard."""
        data_str = str(data_str).strip().lower()
        
        # Mappa dei mesi in italiano
        mesi = {
            'gennaio': '01', 'febbraio': '02', 'marzo': '03', 'aprile': '04',
            'maggio': '05', 'giugno': '06', 'luglio': '07', 'agosto': '08',
            'settembre': '09', 'ottobre': '10', 'novembre': '11', 'dicembre': '12'
        }
        
        # Sostituisce il mese a lettere (es. "31 marzo 2026" -> "31/03/2026")
        for mese_nome, mese_num in mesi.items():
            if mese_nome in data_str:
                data_str = re.sub(fr'\s+{mese_nome}\s+', f'/{mese_num}/', data_str)
                break
        
        data_str = data_str.replace('-', '/')
        
        # Converte l'eventuale formato ISO YYYY/MM/DD in DD/MM/YYYY
        m_iso = re.match(r'^(\d{4})/(\d{2})/(\d{2})$', data_str)
        if m_iso:
            return f"{m_iso.group(3)}/{m_iso.group(2)}/{m_iso.group(1)}"
            
        return data_str

    def _estrai_dati_regex(self, testo):
        """Regex per P.IVA, Numeri Documento e Date."""
        dati = {"supplier_vat": "", "customer_vat": "", "invoice_number": "", "invoice_date": ""}
        pivas = list(dict.fromkeys(re.findall(r'(?i)\b(?:IT)?\s*(\d{11})\b', testo)))
        if len(pivas) >= 1: dati["supplier_vat"] = pivas[0]
        if len(pivas) >= 2: dati["customer_vat"] = pivas[1]
        
        # --- NUOVA LOGICA ESTRAZIONE DATA ---
        date_patterns = [
            # 1. Cerca date testuali vicine a "data" o "del" (es. "del 31 Marzo 2026")
            r'(?i)(?:data|del)[\s:]*(\d{1,2}\s+(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+\d{4})',
            # 2. Cerca formato ISO (es. 2026-03-31)
            r'\b(\d{4}[/-]\d{2}[/-]\d{2})\b',
            # 3. Cerca formato Standard (es. 31/03/2026)
            r'\b(\d{2}[/-]\d{2}[/-]\d{4})\b',
        ]
        
        for p in date_patterns:
            matches = re.findall(p, testo)
            if matches:
                # Prende la prima data rilevata e la standardizza in automatico
                dati["invoice_date"] = self._standardizza_data(matches[0])
                break
        # ------------------------------------

        num_patterns = [
            r'(?i)([a-z0-9\-]+\s*/\s*[a-z0-9\-]+(?:/[a-z0-9\-]+)*)\s+del\s+(?:\d{2}[/-]\d{2}[/-]\d{4}|\d{1,2}\s+[a-z]+\s+\d{4})',
            r'(?i)(?:fattura|n[°.]|numero)[\s:]*([A-Z0-9\-/]*\d+[A-Z0-9\-/]*)'
        ]
        for p in num_patterns:
            m = re.search(p, testo)
            if m: 
                dati["invoice_number"] = m.group(1).strip()
                break
        return dati

def parse_invoice_pdf(file_path, progress_cb=None):
    parser = RegexInvoiceParser()
    return parser.processa_fattura(file_path, progress_callback=progress_cb)

