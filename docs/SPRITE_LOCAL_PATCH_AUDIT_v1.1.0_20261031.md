# Correzioni locali: interfaccia completa e prova ImageGen — v1.1.0

31 ottobre 2026. Fonte: richiesta utente di completare importazione a dimensioni diverse, flusso browser, revisione collegata al progetto e prova reale. Evoluzione dell'audit v1.0, pipeline della PR #94; rapporto delle verifiche locali prima della pubblicazione nella PR #94.

## Revisioni e ambito

Riletta la lista delle PR aperte prima dell’intervento: #92 `96312a3bb56ebdcf9cb070327dd049f4c0c2a25d`, #94 `e25dcfec976496e734db3152f754b132ed6cec83`, #96 `495654f05b5a9f137200ffed76cfe5c06b6315a3`; restano aperte anche #93, #95 e #90. Al controllo finale main è avanzato a `d504feec264912a30243be972e8327964edf0d09`: la PR #96 è stata integrata alle 08:01:01 UTC, aggiungendo soltanto il piano di cattura versionato. AGENTS.md è invariato; i 21 file del ciclo approvato sono stati confrontati anche con questa tree finale. Questa integrazione remota non è stata eseguita da questo lavoro.

La proposta di protocollo v14 conserva la v13 di #92; il rimando vincolante di AGENTS.md resta alla v12 pubblicata. In v14 è aggiornato soltanto il link alla guida operativa v1.1, senza cambiare i vincoli normativi.

Nessuna modifica agli asset approvati o al runtime. I 38 file locali in `assets/` sono stati inventariati prima del lavoro e confrontati alla fine. La generazione e tutti i derivati sono in `artifacts/`. Nessun commit, upload o merge: l'utente ha richiesto anteprime prima di qualsiasi caricamento GitHub. Per questa prova il prompt è stato quindi conservato nel fascicolo locale immutabile prima della chiamata, senza dichiarare un checkpoint remoto inesistente. Il workspace non ha `.git`.

## Funzionalità completate

| Punto aperto | Comportamento finale |
| --- | --- |
| Output del generatore più grande o con proporzioni diverse | Nessun resize implicito. Mapping uniforme esplicito `fit` oppure scala/offset manuali, o fit da landmark nativi con scala abilitata. Matrice composta e dimensioni registrate; copertura della maschera obbligatoria. Nessuno stretching anisotropo |
| Flusso completo browser | Prepara richiesta e ZIP, seleziona riferimenti approvati, registra prompt, carica PNG, indica landmark sulle due immagini, verifica un'anteprima senza applicare, poi inserisce la correzione nella ricetta condivisa |
| Revisione legata al candidato | Stato derivato da decisioni append-only legate agli hash di candidato/progetto; visibile dopo riapertura. Un progetto modificato non eredita un'approvazione incompatibile. Reiezione ripristina la ricetta precedente del frame, con undo, preservando gli altri frame |
| Diagnostica locale leggibile | Confronto ingrandito del crop, frame completo e GIF. Report tecnico distinto dalla revisione artistica. I replay non creano un secondo bersaglio di approvazione |
| Prova reale ImageGen | Un vero PNG 1254×1254 è stato importato nel contesto 152×152 del Cerbero con landmark, maschera e sfumatura interna. PNG generato, sorgenti e metadati conservati; candidato non approvato |

Il browser usa `sprite_patches/browser.py` come adattatore dei moduli esistenti. `patches.js` annota e invia ricette; non renderizza una seconda versione dei pixel. Il confronto esterno alla maschera riguarda RGBA nel frame nativo prima dell'allineamento globale.

## Prova reale e provenienza

Sorgente: `assets/hell-race/production/cerbero/run-stabilized-v1/source-sheet.png`, SHA-256 `a8f1805b1e52e036504c54b31d8bf57adbe57b078a64afb65b653a0d6bee4f8c`.

Intervento: contorno e cerniera della mandibola inferiore della testa centrale del frame 1, mantenendo posa e connessioni. È un candidato di prova su un dettaglio da valutare, non una nuova diagnosi approvata o un cambio dell'asset canonico.

Fascicolo locale: `artifacts/sprite-editor/patch-browser-v1.1/real-trial/`.

- Prima richiesta `patch-001`: il servizio ha rifiutato sei percorsi di riferimento prima della generazione. Errore conservato in `generation-failed-001.json`; nessun PNG generato da quel tentativo.
- Richiesta effettiva `patches/patch-002`: prompt esatto conservato prima della chiamata, crop e maschera separati. Forniti cinque PNG: crop, originale, riferimento A, precedente e successivo. La maschera è applicata deterministicamente al ritorno. Non sono state dichiarate maschere API inesistenti.
- Servizio: `image_gen.imagegen`, `transparent_background=true`. Modello e seed non esposti, quindi non inventati.
- Output originale: `/workspace/generated_images/exec-f69dd746-0b98-46ba-a8cd-75ea3749bd97.png`, 1254×1254; SHA-256 `e121e233fbd905ac4ada1c2cc706ba32b56dbb620e46aa9673a723164002bbc4`. Originale lasciato al suo posto, con copie verificate nel fascicolo e nel tentativo.
- Contesto: `[300,160,452,312]` nel foglio sorgente. Landmark annotati: generato `[439,640]` → crop `[51,84]`; generato `[645,790]` → crop `[78,100]`. Mapping iniziale `fit`, raffinamento uniforme con rotazione, bicubico, sfumatura interna 1 px.
- Trasformazione registrata: `[0.12261303437230499, 0.011611432795367745, -10.258439078477238, -0.011611432795367745, 0.12261303437230499, 10.625076998891245]` (matrice affine 2×3, candidato → crop).
- Tentativo finale verificato sulla revisione consegnata: `patches/patch-002-attempt-003/`; replay `patch-002-attempt-004/`. I tentativi 001/002 erano prove intermedie prima dell'aggiunta del confronto ingrandito; non sono presentati come evidenze della revisione finale.

Esito tecnico: **797 pixel RGBA cambiati dentro maschera, zero fuori**; 747 pixel hanno variazioni di alpha dentro la regione autorizzata. La registrazione globale del corpo è identica alla baseline; gli altri sette frame allineati restano pixel-identici. Replay di PNG finale, atlas, GIF e ricetta byte per byte.

Esito artistico: **da verificare**. Il candidato rende diverso il dettaglio mandibolare e va giudicato per anatomia, raccordi, materiali e continuità dentale. Due landmark adattati perfettamente non sono una validazione indipendente dell'anatomia. La variazione dell'alpha è registrata, non considerata automaticamente un miglioramento. Nessuna approvazione, promozione in `approved/` o verifica runtime del gioco è implicita.

## Verifiche della revisione consegnata

Python 3.12, Pillow 11.3.0, Chromium reale:

- 70 test automatici: mapping esplicito, proporzioni, copertura, landmark nativi, maschere/alpha, snapshot, CLI e replay, HTTP locale, ZIP, stato persistente e legato ai dati, reiezione e ripristino.
- 30 controlli browser di regressione: 9 allineamento, 9 correzioni deterministiche, 6 importazione di ricetta, 6 flusso completo preparazione/importazione/revisione. Questi usano candidati sintetici dichiarati; le dichiarazioni di approvazione nel test servono soltanto a verificare la UI.
- 6 controlli aggiuntivi sul vero output ImageGen, inclusi confronto RGBA, invarianti degli altri frame, playback nel browser e replay.
- Screenshot e GIF reali dell'editor, viewport 1460×980; GIF della prova reale durata **4900 ms**, in `real-trial/browser/real-browser-demo.gif`. GIF del ciclo derivata dai PNG in `patch-002-attempt-003/diagnostics/aligned.gif`. Nessuna delle due è una registrazione del gioco.
- Controlli sintattici Python e JavaScript. CI proposta aggiornata per i nuovi moduli/test; nessuna CI remota eseguita. La matrice Python 3.10/3.12 sarà verificata quando verrà autorizzato il caricamento.

La prova reale si può ripetere senza nuove chiamate generative con `tests/sprite_real_imagegen_browser.py --trial-root <fascicolo>`, usando i file conservati. Non è parte della CI automatica. Per un replay dei soli pixel usare `--patch-replay` con la revisione Python del tool e la versione Pillow registrate nel manifest.

Guida aggiornata: [Correzioni locali v1.1](SPRITE_LOCAL_PATCHES_v1.1.0_20261031.md). L'editor rimane una UI browser con server Python/Pillow locale; non è stato pubblicato un servizio web o aggiunta un'API ImageGen diretta.


## Pubblicazione del tool — autorizzazione del 31/10/2026

Dopo le anteprime l'utente ha autorizzato caricamento e merge del tool a verifiche superate. I riferimenti a nessun upload/CI remota nel rapporto precedente descrivono il checkpoint locale prima di questa autorizzazione. La PR #94 integra il tool e la documentazione; per il merge devono passare la CI del tool e tutta la CI del repository applicabile alla head pubblicata. Il codice Python del motore coincide con quello verificato nella prova reale e nei manifest già consegnati.

L'interfaccia non chiama direttamente ImageGen: la generazione rimane esterna, utilizzabile da ChatGPT/Codex con gli strumenti disponibili nella sessione, oppure manualmente. L'utente ha rinviato una futura integrazione API/browser. Non è richiesto alcun servizio o segreto ImageGen per estrarre, modificare, preparare, importare o riprodurre i pixel. Il candidato artistico della prova non viene promosso né integrato nel gioco.
