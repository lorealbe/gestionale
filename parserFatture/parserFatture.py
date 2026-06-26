import os
import re
import xml.etree.ElementTree as ET
import fitz  # PyMuPDF per il fallback testuale

class InvoiceParser:
    def processa_fattura(self, file_path, progress_callback=None):
        if not os.path.exists(file_path): raise FileNotFoundError("File non trovato.")
        
        # 1. È UN FILE XML? (Metodo infallibile)
        if file_path.lower().endswith('.xml'):
            if progress_callback: progress_callback("Lettura fattura elettronica XML...")
            return self._estrai_da_xml(file_path)

        # 2. È UN PDF? (Metodo euristico/fallback)
        if progress_callback: progress_callback("Estrazione testo dal PDF...")
        testo_estratto = self._estrai_testo_pdf(file_path)
        if not testo_estratto.strip(): raise ValueError("Il PDF non contiene testo digitale.")

        risultato = self._estrai_dati_regex(testo_estratto)
        
        # Usiamo il fallback testuale ottimizzato per le righe prodotto
        if progress_callback: progress_callback("Estrazione righe prodotti...")
        risultato["line_items"] = self._estrai_righe_prodotti_fallback(testo_estratto)
        
        return risultato

    # ==========================================
    # IL MOTORE XML (100% Affidabile, 0 Errori)
    # ==========================================
    def _estrai_da_xml(self, file_path):
        """Estrae i dati chirurgicamente dai tag standard SDI italiani."""
        # Rimuove i namespace dall'XML per facilitare la ricerca dei tag
        it = ET.iterparse(file_path)
        for _, el in it: el.tag = el.tag.split('}', 1)[1] if '}' in el.tag else el.tag
        root = it.root

        def get_text(node, tag, default=""):
            el = node.find(f".//{tag}") if node else None
            return el.text.strip() if el is not None and el.text else default

        dati = {
            "supplier_name": get_text(root, "CedentePrestatore//Denominazione", get_text(root, "CedentePrestatore//Nome") + " " + get_text(root, "CedentePrestatore//Cognome")),
            "supplier_vat": get_text(root, "CedentePrestatore//IdCodice"),
            "customer_name": get_text(root, "CessionarioCommittente//Denominazione"),
            "customer_vat": get_text(root, "CessionarioCommittente//IdCodice"),
            "invoice_number": get_text(root, "DatiGeneraliDocumento/Numero"),
            "invoice_date": get_text(root, "DatiGeneraliDocumento/Data"), # Esce come YYYY-MM-DD
            "taxable_total": get_text(root, "DatiRiepilogo/ImponibileImporto"),
            "vat_total": get_text(root, "DatiRiepilogo/Imposta"),
            "total_amount": get_text(root, "DatiPagamento/ImportoPagamento"),
            "line_items": []
        }

        # Estrazione perfetta delle righe prodotto
        for linea in root.findall(".//DettaglioLinee"):
            dati["line_items"].append({
                "description": get_text(linea, "Descrizione", "-"),
                "quantity": get_text(linea, "Quantita", "1.00"),
                "price": get_text(linea, "PrezzoUnitario", "0.00"),
                "line_total": get_text(linea, "PrezzoTotale", "0.00"),
                "vat": get_text(linea, "AliquotaIVA", "0.00"),
            })

        # Standardizza data in DD/MM/YYYY
        if dati["invoice_date"]: 
            p = dati["invoice_date"].split('-')
            if len(p) == 3: dati["invoice_date"] = f"{p[2]}/{p[1]}/{p[0]}"
            
        return dati

    # ==========================================
    # IL MOTORE PDF (Fallback Ottimizzato)
    # ==========================================
    def _estrai_testo_pdf(self, file_path):
        with fitz.open(file_path) as doc: return "\n".join([pagina.get_text("text") for pagina in doc])

    def _estrai_dati_regex(self, testo):
        dati = {"supplier_vat": "", "customer_vat": "", "invoice_number": "", "invoice_date": "", "taxable_total": "", "vat_total": "", "total_amount": ""}
        
        # Date e Numeri (Manteniamo le tue ottime RegEx)
        pivas = list(dict.fromkeys(re.findall(r'(?i)\b(?:IT)?\s*(\d{11})\b', testo)))
        if len(pivas) >= 1: dati["supplier_vat"] = pivas[0]
        if len(pivas) >= 2: dati["customer_vat"] = pivas[1]
        
        m_data = re.search(r'\b(\d{2}[/-]\d{2}[/-]\d{4}|\d{4}[/-]\d{2}[/-]\d{2})\b', testo)
        if m_data: dati["invoice_date"] = m_data.group(1).replace('-', '/')

        m_num = re.search(r'(?i)(?:fattura|n[°.]|numero)[\s:]*([A-Z0-9\-/]*\d+[A-Z0-9\-/]*)', testo)
        if m_num: dati["invoice_number"] = m_num.group(1).strip()

        # Totali (Ricerca rapida in fondo al testo)
        m_totale = re.search(r'(?i)totale(?!\s+riga).*?((?:\d{1,3}(?:[.,\s]\d{3})+|\d+)[.,]\d{2})\b', testo[len(testo)//2:])
        if m_totale: dati["total_amount"] = m_totale.group(1).replace(' ', '')

        return dati

    def _estrai_righe_prodotti_fallback(self, testo):
        line_items = []
        # Estrazione testuale semplificata: cerca righe che finiscono con pattern [Descrizione] [Qta] [Prezzo] [Totale]
        pattern_riga = r'(?m)^(.+?)\s+(\d+[,.]\d+|\d+)\s+(\d+[,.]\d{2})\s+(\d+[,.]\d{2})$'
        for match in re.finditer(pattern_riga, testo):
            desc, qta, prz, tot = match.groups()
            if not re.search(r'(?i)totale|riepilogo|imponibile', desc):
                line_items.append({"description": desc.strip(), "quantity": qta, "price": prz, "line_total": tot, "vat": ""})
        return line_items

def parse_invoice_pdf(file_path, progress_cb=None):
    return InvoiceParser().processa_fattura(file_path, progress_callback=progress_cb)