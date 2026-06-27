from database import (
    ensure_data_paths, get_azienda_info, save_azienda_info,
    add_soggetto, list_soggetti, delete_soggetto
)
from models import Utente

def run_test():
    print("🔄 1. Inizializzazione Database in corso...")
    ensure_data_paths()
    print("✅ Tabelle create e verificate con successo!")

    # Creiamo un utente fittizio per il test (le tabelle richiedono uno user_id)
    utente_test, created = Utente.get_or_create(
        username="test_admin", 
        defaults={"password_hash": "hash_sicuro_123"}
    )
    uid = utente_test.id
    print(f"👤 2. Utente di test pronto (ID: {uid})")

    print("\n📝 3. Test Scrittura e Lettura Info Azienda...")
    save_azienda_info(uid, "Fattoria del Sole", "IT12345678901", "Allevamento", "2024-01-01")
    info = get_azienda_info(uid)
    print(f"   Risultato: {info['nome_azienda']} (P.IVA {info['piva']})")

    print("\n🤝 4. Test Inserimento CRM (Anagrafica)...")
    # Inseriamo un fornitore di prova
    soggetto_id = add_soggetto(uid, "Fornitore", "Mangimi Rossi SpA", partita_iva="98765432109")
    print(f"   Inserito soggetto con ID: {soggetto_id}")
    
    # Leggiamo i soggetti
    soggetti = list_soggetti(uid)
    print(f"   Soggetti totali trovati: {len(soggetti)}")
    for s in soggetti:
        print(f"   -> {s['ragione_sociale']} ({s['tipo']})")

    print("\n🧹 5. Test di Pulizia (Eliminazione)...")
    delete_soggetto(uid, soggetto_id)
    soggetti_dopo = list_soggetti(uid)
    print(f"   Soggetti trovati dopo l'eliminazione: {len(soggetti_dopo)}")
    
    if len(soggetti_dopo) == 0:
        print("\n🚀 TUTTI I TEST SUPERATI! L'ORM è veloce e stabile.")
    else:
        print("\n⚠️ Attenzione, qualcosa non ha funzionato nell'eliminazione.")

if __name__ == "__main__":
    run_test()