# Editor locale per allineamento e onion skin

Versione 1.2.0 · 31 ottobre 2026 · Europe/Rome.

Estensione locale del tool `scripts/sprite_postprocess.py` della PR #94. Introduce l’editor visuale dei punti e il confronto prima/dopo richiesti dall’utente. La modifica è preparata per revisione locale: nessun caricamento su GitHub e nessuna modifica al gioco o agli asset originali.

## Avvio

Servono Python 3.10+ e Pillow. Per aprire l’editor non servono Node, Playwright o una connessione Internet; Playwright e Chromium servono soltanto per il test automatico dell’interfaccia.

```bash
python3 -m pip install -r requirements-test.txt
python3 scripts/sprite_postprocess.py \
  assets/hell-race/production/cerbero/run-stabilized-v1/source-sheet.png \
  --columns 4 --rows 2 \
  --landmarks assets/hell-race/production/cerbero/run-stabilized-v1/landmarks.json \
  --editor --out artifacts/sprite-editor/project
```

Aprire nel proprio browser l’indirizzo `http://127.0.0.1:PORTA` stampato dal comando. Per una porta fissa aggiungere, per esempio, `--port 8765`. Il server ascolta solo su localhost; CTRL+C lo chiude. Non usa servizi esterni e non contiene funzioni di pubblicazione o caricamento su GitHub.

Per un’altra tavola, cambiare sorgente e griglia. `--landmarks` è facoltativo: senza annotazioni si parte da punti vuoti, con allineamento provvisorio. Le opzioni di estrazione del tool originale (`--mode`, `--min-area`, `--alpha-threshold`) continuano a funzionare. L’opzione batch `--body-roi` riguarda l’algoritmo automatico della CLI: nell’editor la registrazione si basa sui punti annotati.

## Flusso di lavoro

1. Scegliere il frame di riferimento dal pannello sinistro.
2. Selezionare un punto, poi cliccare sull’originale per aggiungerlo o trascinarlo per correggerlo. Si possono anche modificare X/Y e il peso di affidabilità nei campi numerici.
3. Annotare gli stessi nomi sui frame pertinenti. I nomi non creano automaticamente punti nelle altre pose. Usare punti stabili sul corpo e omettere quelli occlusi, invece di inventarli.
4. Controllare il risultato a destra. Entrambe le viste usano lo stesso canvas e la stessa scala. **Affiancati** mostra originale e allineato; **Sovrapposti** aggiunge la sagoma originale in rosso e quella allineata in ciano.
5. Attivare **Onion skin** per confrontare il frame corrente con il precedente in rosso e il successivo in ciano. L’opacità è regolabile e i vicini includono il raccordo ultimo→primo.
6. Usare la timeline, i pulsanti precedente/successivo o le frecce della tastiera. Spazio avvia/ferma la riproduzione; la velocità di revisione è separata dalla durata esportata di ciascuna posa.
7. **Salva progetto** scrive `project.json` nella cartella `--out`. **Apri progetto** carica un JSON locale e ne verifica sorgente e ritagli. File appartenenti a un’altra tavola sono rifiutati.
8. **Esporta PNG e GIF** crea una nuova cartella `export-001`, `export-002`, ecc. Gli export precedenti restano conservati.

La modifica di un punto ferma la riproduzione. Zoom e scorrimento non cambiano le coordinate salvate, che rimangono riferite alla tavola sorgente intera. **Adatta** riporta entrambe le viste a una scala leggibile. **Annulla** e **Ripristina** conservano i cambiamenti dei punti e delle impostazioni; le scorciatoie sono Ctrl/Cmd+Z e Ctrl/Cmd+Maiusc+Z quando non si sta scrivendo in un campo.

## Movimento, scala e affidabilità

Le coordinate **Spostamento X/Y**, in “Movimento e scala”, conservano lo spostamento corporeo intenzionale rispetto al riferimento. Il valore zero stabilizza la posizione dei punti: non costituisce una traiettoria fisica automaticamente corretta.

L’allineamento predefinito usa una sola traslazione globale per frame. La scala uniforme è facoltativa e viene stimata dagli stessi landmark. La registrazione globale non introduce rotazione o scale diverse sui due assi. La rotazione di una singola parte è disponibile separatamente nella scheda Correggi. “Campionamento pixel art” seleziona il nearest-neighbor; le trasformazioni frazionarie usano altrimenti bicubica, mentre una traslazione intera conserva i pixel.

L’editor riusa direttamente estrazione, fit pesato e rendering della CLI. Con “Applica allineamento del corpo” attivo, i frame senza punti in comune rimangono in disposizione provvisoria e bloccano l’esportazione; non vengono inventati punti. Un solo punto può inizializzare una traslazione, ma la verifica rimane esplicitamente provvisoria. Tre punti non allineati consentono una stima più informativa, senza certificare l’anatomia. Il valore RMS misura solo la corrispondenza dei landmark annotati. Osservare separatamente proporzioni, appoggi, articolazioni e movimento previsto.

## File esportati

- `aligned/NNN.png`: frame RGBA allineati.
- `onion/NNN.png`: frame con vicini sovrapposti.
- `atlas.png`: tavola RGBA nel numero di colonne richiesto.
- `raw.gif`, `aligned.gif`, `onion.gif`: loop locali dei PNG, con palette condivisa e durate dichiarate.
- `landmarks.json`: progetto modificabile, con hash sorgente, punti, pesi, ancoraggi e movimento intenzionale.
- `manifest.json`: griglia dei frame, matrici sorgente→preview/output, residui e hash degli allineati.

L’editor usa l’unione degli ingombri originali e allineati per mantenere **anteprima ed esportazione identiche** e rendere confrontabili le viste. La CLI batch tradizionale continua a usare l’ingombro degli allineati; importando lo stesso JSON nella CLI le relazioni fra pose coincidono, ma il padding e la traslazione comune del canvas possono differire. Non confondere quel cambiamento globale del riquadro con un diverso allineamento relativo.

Gli export sono preparati in una directory temporanea e diventano disponibili solo a scrittura completata. Gli originali non vengono sovrascritti. Le chiamate di modifica del server richiedono il token della sessione locale e rifiutano richieste provenienti da altre origini; nessun percorso arbitrario del filesystem è pubblicato dal server.

## Verifiche e anteprima di revisione

```bash
python3 -m unittest discover -s tests -p 'test_sprite*.py' -v
python3 tests/sprite_editor_browser.py
```

Il test browser richiede Chromium (default `/usr/bin/chromium`, configurabile con `CHROMIUM_PATH`) e il pacchetto Cerbero già salvato in `assets/hell-race/production/cerbero/run-stabilized-v1/`. Produce una GIF **realmente acquisita da Chromium**, screenshot e rapporto in `artifacts/sprite-editor/review/`. Copre trascinamento e coordinate a zoom diversi, scorrimento, undo/redo, confronto/onion skin, salvataggio e riapertura, rifiuto di un progetto di altra sorgente, export e riproduzione del raccordo 8→1.

La GIF dell’editor mostra l’interfaccia locale: non è una registrazione del gioco. I GIF presenti nelle cartelle esportate sono invece diagnostiche dei PNG. La suite del gioco non è stata eseguita per questa modifica isolata dello strumento; nessun risultato di integrazione runtime viene dichiarato.

Anteprime di revisione: `artifacts/sprite-editor/review/editor.png` e `editor-demo.gif`. Nessun HTML autonomo viene consegnato come anteprima; i file HTML/JS/CSS sotto `scripts/sprite_editor/` sono i sorgenti dell’interfaccia, serviti dal processo Python locale.


## Correzioni locali deterministiche — versione 1.1

La scheda **Correggi** aggiunge maschere poligonali, parti con pivot, pennello, gomma e timbro clone. L’interfaccia rimane nel browser; Python e Pillow eseguono le operazioni sul computer che avvia il server locale. Non servono estensioni del browser, Node o servizi di generazione immagini. Per usarlo con un solo collegamento senza Python sul proprio computer occorre ospitare il server su un servizio online: questa versione non è stata pubblicata.

### Parti, maschere e pivot

1. Selezionare un frame e passare a **Correggi → Seleziona parte**.
2. Cliccare i vertici del contorno sull’originale, poi **Chiudi maschera**. La selezione campiona sempre i pixel del frame originale.
3. Scegliere esplicitamente il pivot sull’articolazione visibile. Il centro geometrico iniziale è solo un indicatore di lavoro: la rotazione e la scala restano disabilitate finché non viene impostato un pivot.
4. Usare Sposta X/Y, Rotazione e Scala uniforme. La parte può anche essere trascinata dalla sua maschera sull’originale. L’angolo positivo ruota in senso orario sullo schermo.
5. Controllare il risultato a destra, i frame vicini e l’onion skin. La selezione blu indica i pixel sorgenti, la sagoma verde tratteggiata indica la loro destinazione e la croce gialla il pivot scelto.

“Rimuovi la posizione originale” sposta la parte; disattivandolo si crea una copia. Le zone scoperte rimangono trasparenti: il tool non inventa le superfici mancanti. La tela cresce quando occorre, per conservare punte e arti trasformati; l’esportazione usa la stessa tela della preview. Non vengono introdotti scale differenti sui due assi o warp.

Una parte non può spostare un punto usato per registrare il corpo: il tool richiede di scegliere riferimenti stabili fuori dalla maschera. È consentito lasciare un riferimento esattamente fermo sul pivot. Le parti e i rispettivi attacchi richiedono comunque una verifica anatomica: una trasformazione matematicamente corretta non certifica un’articolazione.

### Ritocco dei pixel

- **Pennello** registra tratti e colore RGBA; “Campiona colore” legge il pixel dell’originale senza le guide sovrapposte. Il raggio minimo 0,5 permette un tratto di un pixel nativo.
- **Gomma** rende trasparenti i pixel nel risultato, rimuovendo anche i relativi colori nascosti. Il file originale resta invariato.
- **Timbro clone** richiede prima un’origine sull’originale dello stesso frame. Poi si disegna sulla destinazione. Il campione resta quello originale anche se altri tratti hanno già modificato la stessa zona. La ricetta supporta anche un altro frame sorgente tramite `source_frame`, utilizzabile via script.

I tratti e le maschere si applicano nell’ordine mostrato. Si possono disattivare, eliminare o anticipare/posticipare con Prima/Dopo. Annulla/Ripristina funziona anche per queste correzioni. I campioni delle parti e del clone provengono dagli originali immutabili; per esempio, un ritocco destinato a una parte ruotata va applicato dopo il suo spostamento. La parte con trasformazione identità ripristina i pixel originali della sua maschera, conservandoli esattamente.

### Ricetta e riproducibilità

`project.json` e `landmarks.json` conservano un elenco `edits` per ogni frame e la versione `local_edits_version`. Ogni operazione registra selezione o tratto, pivot, trasformazione, colore/campione ed eventuale disattivazione. Il motore `scripts/sprite_edits.py` viene condiviso da editor e CLI: usando un progetto con `edits` anche l’esportazione batch applica le correzioni.

A parità di immagini sorgenti, ricetta e ambiente di esecuzione (versioni del motore, Python e Pillow), i PNG sono ripetibili byte per byte. Una traslazione intera copia i pixel; per rotazioni o scale frazionarie il ricampionamento dichiarato può cambiare i bordi in modo deterministico. Il manifest riporta la versione del motore, le operazioni applicate e le matrici. I dati non vengono inviati a imagegen o a GitHub.

Le coordinate di selezioni, pivot e tratti sono quelle della tavola sorgente, prima della registrazione globale. Le correzioni cambiano il disegno, mantenendo il sistema di riferimento dei landmark corporei. Il risultato corretto viene poi posizionato con lo stesso allineamento del corpo. Il canvas originale e quello corretto condividono una sola vista, e gli originali rimangono disponibili per rifare l’export dall’inizio.

### Verifiche aggiuntive

I test raster verificano maschere, traslazioni esatte, rotazioni di 90°, espansione senza ritagli, protezione dei landmark, campioni clone immutabili, pennello/gomma e ripetibilità PNG. Il test `tests/sprite_local_edits_browser.py` esercita nel browser selezione, pivot, rotazione, ritocco, annullamento, salvataggio e due esportazioni della stessa ricetta. Le modifiche mostrate nel demo sono prove dell’interfaccia, non nuove pose approvate per il gioco.


### Ritocco senza allineamento

Per usare solo maschere e ritocchi, aprire Allinea e disattivare **Applica allineamento del corpo**. Si può così esportare anche senza landmark. L’opzione è salvata come `align_body: false` nel progetto; la CLI la riconosce e offre anche `--no-align`. Quando la registrazione è disattivata, i vecchi landmark non vincolano le parti. Riattivandola, scegliere riferimenti corporei stabili e controllare il risultato.

Gli ancoraggi funzionali già annotati in `anchors` seguono automaticamente le parti spostate: il manifest registra la loro nuova posizione e se il campione cade su un pixel visibile. Le copie mantengono l’ancoraggio dell’originale, evitando di inventare un nuovo identificatore. La visibilità del pixel è solo un controllo tecnico; l’appoggio anatomico richiede una verifica separata.


## Correzioni esterne circoscritte — novità v1.2

Il pulsante **Correzioni ImageGen** apre preparazione, importazione e revisione nella stessa UI. Supporta PNG a risoluzione diversa, mapping uniforme esplicito, landmark sulle due immagini native, anteprima mascherata, caricamento della ricetta, revisioni persistenti e ripristino del frame precedente. La generazione resta esterna; il tool non presuppone API accessibili.

Seguire la [guida alle correzioni locali v1.1](SPRITE_LOCAL_PATCHES_v1.1.0_20261031.md). Nessun asset approvato viene sovrascritto. L'approvazione della singola correzione non implica integrazione o merge. Limite delle richieste browser: 24 MB; singolo PNG: 16 milioni di pixel. La pubblicazione del tool e la CI sono seguite nella [PR #94](https://github.com/rickymusu-bit/quiz/pull/94); il merge è autorizzato dall’utente solo dopo le verifiche applicabili.
