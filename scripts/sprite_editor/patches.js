"use strict";

(() => {
  const dialog = $("patch-dialog");
  const view = {
    busy: false,
    step: "prepare",
    requests: [],
    attempts: [],
    request: null,
    candidate: null,
    targetImage: null,
    candidateImage: null,
    pairs: [],
    target: null,
    attempt: null,
    previewKey: null,
  };
  const fields = [
    ["subject", "Identità del soggetto", "Cerbero canonico rosso/carnoso"],
    ["defect", "Difetto osservato", "Descrivi il difetto circoscritto"],
    ["correction", "Unica correzione richiesta", "Quale dettaglio ricostruire"],
    [
      "geometry",
      "Geometria e movimento",
      "Orientamento, proporzioni e posa da mantenere",
    ],
    [
      "connections",
      "Articolazioni e connessioni obbligatorie",
      "Punti di attacco da preservare",
    ],
    [
      "preserve",
      "Elementi e stile invariati",
      "Palette, luce, materiali, parti protette",
    ],
  ];
  const checks = {
    defect_fixed: "Il difetto individuato è risolto",
    identity: "Identità grafica preservata",
    anatomy_mechanics: "Anatomia e meccanica coerenti",
    neighbor_continuity: "Continuità con entrambi i vicini e al raccordo",
    anchors: "Bocche, artigli, ruote e contatti verificati",
    materials_lighting: "Materiali, colori e illuminazione coerenti",
    no_halos_seams: "Assenza di aloni, bordi e deformazioni nuove",
    final_scale: "Verifica alla scala e alla velocità finali",
  };
  const labels = {
    pending_visual_review: "Da verificare",
    approved: "Approvata",
    rejected: "Scartata",
    unverified_review: "Revisione precedente da verificare",
    unavailable: "Fascicolo non disponibile",
  };
  fields.forEach(([key, label, placeholder]) => {
    const element = document.createElement("label");
    element.textContent = label;
    const input = document.createElement("input");
    input.id = "patch-" + key;
    input.placeholder = placeholder;
    element.append(input);
    $("patch-fields").append(element);
  });
  Object.entries(checks).forEach(([key, label]) => {
    const row = document.createElement("label");
    row.className = "check";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.id = "patch-check-" + key;
    row.append(input, document.createTextNode(label));
    $("patch-review-checks").append(row);
  });

  function fail(message) {
    $("patch-error").hidden = !message;
    $("patch-error").textContent = message;
  }
  function message(text) {
    $("patch-message").textContent = text;
  }
  function refresh() {
    if (!state.project) return;
    const selected = window.SpriteLocal?.selection();
    const usable =
      selected?.type === "part" &&
      selected.rotation_deg === 0 &&
      selected.scale === 1 &&
      selected.translate.every((v) => v === 0);
    $("patch-selection").textContent = usable
      ? `Frame ${state.frame + 1} · maschera «${selected.name}» selezionata`
      : "In Correggi disegna e chiudi una maschera, selezionala e lasciala senza trasformazioni prima di preparare l’intervento.";
    $("patch-prepare").disabled =
      view.busy ||
      !usable ||
      !["anatomy_detail", "missing_detail", "hidden_surface"].includes(
        $("patch-error-type").value,
      );
    $("patch-apply").disabled =
      view.busy || !view.previewKey || view.previewKey !== signature();
  }
  async function run(action) {
    if (view.busy) return;
    view.busy = true;
    dialog.setAttribute("aria-busy", "true");
    fail("");
    message("Operazione locale in corso…");
    const disabled = new Map(
      [...dialog.querySelectorAll("button")].map((b) => [b, b.disabled]),
    );
    for (const button of disabled.keys()) button.disabled = true;
    try {
      await action();
    } catch (e) {
      fail(e.message);
      message("");
    } finally {
      view.busy = false;
      dialog.removeAttribute("aria-busy");
      for (const [button, value] of disabled) button.disabled = value;
      refresh();
    }
  }
  function step(name) {
    view.step = name;
    for (const key of ["prepare", "import", "review"]) {
      $("patch-" + key + "-panel").hidden = key !== name;
      $("patch-tab-" + key).classList.toggle("active", key === name);
      $("patch-tab-" + key).setAttribute("aria-pressed", String(key === name));
    }
    dialog.scrollTop = 0;
  }
  function fillSelect(id, entries, selected) {
    const select = $(id);
    select.replaceChildren();
    for (const entry of entries) {
      const option = document.createElement("option");
      option.value = entry.id;
      option.textContent = `${entry.id} · frame ${entry.frame}`;
      select.append(option);
    }
    if (entries.some((e) => e.id === selected)) select.value = selected;
  }
  async function reload() {
    const response = await fetch("/api/patch/list");
    if (!response.ok) throw new Error("Impossibile leggere i fascicoli locali");
    const data = await response.json();
    view.requests = data.requests;
    view.attempts = data.attempts;
    fillSelect("patch-request", view.requests, view.request?.id);
    fillSelect("patch-attempt", view.attempts, view.attempt?.id);
  }
  function invalidate() {
    view.previewKey = null;
    $("patch-composite").hidden = true;
    $("patch-transform").textContent = "";
    refresh();
  }
  function registration() {
    const result = {
      landmarks: clone(view.pairs),
      allow_scale: $("patch-allow-scale").checked,
      allow_rotation: $("patch-allow-rotation").checked,
      nearest: $("patch-nearest").checked,
      max_residual_px: Number($("patch-tolerance").value),
      feather_px: Number($("patch-feather").value),
    };
    const mode = $("patch-mapping").value;
    if (mode === "fit") result.input_mapping = { mode };
    if (mode === "uniform")
      result.input_mapping = {
        mode,
        scale: Number($("patch-input-scale").value),
        offset: [
          Number($("patch-offset-x").value),
          Number($("patch-offset-y").value),
        ],
      };
    return result;
  }
  function signature() {
    return JSON.stringify({
      request: view.request?.id,
      upload: view.candidate?.id,
      registration: registration(),
    });
  }
  function fileChecks(container, names, links = false) {
    $(container).replaceChildren();
    for (const name of names) {
      if (links) {
        const a = document.createElement("a");
        a.href = view.request.url + name;
        a.textContent = name;
        a.download = name.split("/").pop();
        a.className = "patch-file-link";
        $(container).append(a, document.createTextNode(" · "));
      } else {
        const label = document.createElement("label");
        label.className = "check";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.value = name;
        label.append(input, document.createTextNode(name));
        $(container).append(label);
      }
    }
  }
  async function setRequest(identifier) {
    view.request = view.requests.find((r) => r.id === identifier) || null;
    view.candidate = null;
    view.candidateImage = null;
    view.targetImage = null;
    view.pairs = [];
    view.target = null;
    $("patch-candidate").value = "";
    invalidate();
    if (!view.request) return;
    $("patch-request").value = identifier;
    $("patch-saved-prompt").textContent = view.request.prompt;
    $("patch-download").href = view.request.archive_url;
    $("patch-download").download = identifier + ".zip";
    fileChecks(
      "patch-input-files",
      [...view.request.required_files, ...view.request.optional_files],
      true,
    );
    fileChecks("patch-supplied-files", [
      ...view.request.required_files,
      ...view.request.optional_files,
    ]);
    $("patch-prompt-confirmed").checked = false;
    view.targetImage = await image(view.request.url + "context.png");
    renderPoints();
    drawImages();
    $("patch-dimensions").textContent =
      `Contesto ${view.targetImage.width} × ${view.targetImage.height} px · nessun adattamento implicito.`;
  }
  function setAttempt(identifier) {
    view.attempt = view.attempts.find((a) => a.id === identifier) || null;
    if (!view.attempt) {
      $("patch-before-after").hidden = true;
      $("patch-crop-comparison").hidden = true;
      $("patch-review-status").textContent = "Nessun tentativo conservato";
      return;
    }
    $("patch-attempt").value = identifier;
    const review = view.attempt.review;
    $("patch-review-status").textContent =
      `${labels[review.status] || review.status}${review.reviewer ? " · " + review.reviewer : ""}${review.file ? " · " + review.file : ""}`;
    $("patch-crop-comparison").hidden = !view.attempt.has_crop_comparison;
    if (view.attempt.has_crop_comparison)
      $("patch-crop-comparison").src =
        view.attempt.url + "before-after-crop.png";
    $("patch-full-comparison").open = !view.attempt.has_crop_comparison;
    $("patch-before-after").src = view.attempt.url + "before-after.png";
    $("patch-before-after").hidden = false;
    $("patch-diagnostic").src = view.attempt.url + "diagnostics/aligned.gif";
    for (const key of Object.keys(checks))
      $("patch-check-" + key).checked = false;
    $("patch-review-notes").value = "";
    $("patch-review-evidence").value = "";
  }
  function drawImages() {
    for (const [id, im, kind] of [
      ["patch-target-canvas", view.targetImage, "target"],
      ["patch-generated-canvas", view.candidateImage, "generated"],
    ]) {
      const canvas = $(id),
        ctx = canvas.getContext("2d");
      canvas.width = im?.width || 1;
      canvas.height = im?.height || 1;
      if (!im) continue;
      ctx.drawImage(im, 0, 0);
      const zoom = Number($("patch-view-zoom").value),
        display = Math.min(1, 500 / im.width, 310 / im.height) * zoom;
      canvas.style.width = im.width * display + "px";
      canvas.style.height = im.height * display + "px";
      if (kind === "target" && view.request?.mask_polygon) {
        ctx.save();
        ctx.strokeStyle = "#65dcec";
        ctx.fillStyle = "#65dcec33";
        ctx.lineWidth = 1 / display;
        ctx.beginPath();
        view.request.mask_polygon.forEach(([x, y], i) => {
          x -= view.request.crop_box[0];
          y -= view.request.crop_box[1];
          if (i) ctx.lineTo(x, y);
          else ctx.moveTo(x, y);
        });
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
        ctx.restore();
      }
      const points = view.pairs.map((pair, i) => ({
        point: pair[kind],
        label: i + 1,
      }));
      if (kind === "target" && view.target)
        points.push({ point: view.target, label: "?" });
      for (const {
        point: [x, y],
        label,
      } of points) {
        ctx.save();
        ctx.lineWidth = 1.5 / display;
        ctx.strokeStyle = "#c4ed8c";
        ctx.fillStyle = "#c4ed8c";
        ctx.beginPath();
        ctx.arc(x, y, 5 / display, 0, 2 * Math.PI);
        ctx.stroke();
        ctx.font = `${12 / display}px system-ui`;
        ctx.fillText(String(label), x + 8 / display, y - 5 / display);
        ctx.restore();
      }
    }
  }
  function renderPoints() {
    $("patch-point-list").replaceChildren();
    view.pairs.forEach((pair, i) => {
      const row = document.createElement("div");
      row.className = "patch-point-row";
      const title = document.createElement("span");
      title.textContent = `Punto ${i + 1} · orig. / gen.`;
      row.append(title);
      for (const key of ["target", "generated"])
        for (let axis = 0; axis < 2; axis++) {
          const input = document.createElement("input");
          input.type = "number";
          input.step = "0.1";
          input.value = pair[key][axis];
          input.setAttribute(
            "aria-label",
            `Punto ${i + 1} ${key} ${axis === 0 ? "X" : "Y"}`,
          );
          input.onchange = () => {
            pair[key][axis] = Number(input.value);
            invalidate();
            drawImages();
          };
          row.append(input);
        }
      const remove = document.createElement("button");
      remove.textContent = "×";
      remove.setAttribute("aria-label", `Elimina landmark ${i + 1}`);
      remove.onclick = () => {
        view.pairs.splice(i, 1);
        invalidate();
        renderPoints();
        drawImages();
      };
      row.append(remove);
      $("patch-point-list").append(row);
    });
  }
  async function base64File(file) {
    return await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result.split(",")[1]);
      reader.onerror = () => reject(new Error("Impossibile leggere il PNG"));
      reader.readAsDataURL(file);
    });
  }
  async function loadProject(project, frame, operation) {
    pause();
    history();
    state.project = project;
    state.frame = frame ?? state.frame;
    state.selected = null;
    changed();
    clearTimeout(previewTimer);
    await updatePreview();
    if (operation) window.SpriteLocal?.selectOperation(operation);
  }

  $("patch-open").onclick = () =>
    run(async () => {
      pause();
      dialog.showModal();
      await reload();
      if (!view.request && view.requests.length)
        await setRequest(view.requests.at(-1).id);
      if (!view.attempt && view.attempts.length)
        setAttempt(view.attempts.at(-1).id);
      step(view.step);
      refresh();
      message(
        "Originali conservati. La generazione resta un passaggio esterno.",
      );
    });
  $("patch-close").onclick = () => dialog.close();
  for (const name of ["prepare", "import", "review"])
    $("patch-tab-" + name).onclick = () => {
      fail("");
      step(name);
    };
  $("patch-error-type").onchange = () => {
    refresh();
    if (
      !["anatomy_detail", "missing_detail", "hidden_surface"].includes(
        $("patch-error-type").value,
      )
    )
      message(
        "Questo errore richiede postprocessing, un nuovo keyframe o un nuovo frame, secondo la classificazione selezionata.",
      );
  };
  $("patch-compose").onclick = () => {
    const f = Object.fromEntries(
      fields.map(([key]) => [key, $("patch-" + key).value.trim()]),
    );
    $("patch-prompt").value =
      `Soggetto canonico: ${f.subject}. Correggi esclusivamente questo difetto: ${f.defect}. Unica modifica: ${f.correction}. Geometria e movimento: ${f.geometry}. Connessioni obbligatorie: ${f.connections}. Preserva: ${f.preserve}. Modifica solo la regione indicata nel ritaglio di contesto, mantieni inquadratura e proporzioni. Restituisci un singolo PNG del ritaglio corretto. Usa originale, riferimenti approvati e vicini allegati per identità e continuità.`;
    message(
      "Bozza composta: rileggila prima di conservare il prompt e inviarlo al generatore.",
    );
  };
  $("patch-prepare").onclick = () =>
    run(async () => {
      const selected = window.SpriteLocal?.selection();
      if (selected?.type !== "part")
        throw new Error("Seleziona prima una maschera nell’editor");
      const spec = Object.fromEntries(
        fields.map(([key]) => [key, $("patch-" + key).value.trim()]),
      );
      Object.assign(spec, {
        frame: state.frame + 1,
        error_type: $("patch-error-type").value,
        mask_from_edit: selected.id,
        context_padding: Number($("patch-padding").value),
        prompt: $("patch-prompt").value,
      });
      const references = await Promise.all(
        [...$("patch-references").files].map(async (file) => ({
          png: await base64File(file),
          name: file.name,
          revision: $("patch-reference-revision").value,
          role: "Riferimento canonico approvato",
        })),
      );
      const result = await post("/api/patch/prepare", {
        project: state.project,
        spec,
        references,
        references_approved: $("patch-references-approved").checked,
        use_source_reference: $("patch-use-source").checked,
      });
      await reload();
      await setRequest(result.id);
      step("import");
      message(
        `Pacchetto ${result.id} pronto. Scaricalo e invia i materiali al generatore.`,
      );
    });
  $("patch-request").onchange = () =>
    run(async () => {
      await setRequest($("patch-request").value);
      message("Richiesta caricata senza cambiare il progetto corrente.");
    });
  $("patch-resume").onclick = () =>
    run(async () => {
      if (!view.request) throw new Error("Seleziona una richiesta");
      const result = await post("/api/patch/resume", {
        request_id: view.request.id,
      });
      await loadProject(result.project, view.request.frame - 1);
      message(
        "Ripreso il progetto conservato nella richiesta. Puoi annullare il cambio con Annulla.",
      );
    });
  $("patch-candidate").onchange = () =>
    run(async () => {
      const file = $("patch-candidate").files[0];
      if (!file || !view.request)
        throw new Error("Seleziona una richiesta e un PNG candidato");
      const result = await post("/api/patch/upload", {
        request_id: view.request.id,
        png: await base64File(file),
      });
      view.candidate = result;
      view.candidateImage = await image(result.url);
      view.pairs = [];
      view.target = null;
      invalidate();
      renderPoints();
      drawImages();
      $("patch-provenance").value = file.name;
      $("patch-dimensions").textContent =
        `Originale ${view.targetImage.width} × ${view.targetImage.height} px · candidato ${result.size.join(" × ")} px. Scegli esplicitamente l’adattamento o usa landmark con scala.`;
      message(
        "PNG caricato. Verifica inquadratura, landmark e maschera prima del reinserimento.",
      );
    });
  for (const [id, kind] of [
    ["patch-target-canvas", "target"],
    ["patch-generated-canvas", "generated"],
  ])
    $(id).onclick = (event) => {
      if (view.busy || !view.targetImage || !view.candidateImage) return;
      const canvas = $(id),
        box = canvas.getBoundingClientRect(),
        p = [
          ((event.clientX - box.left) * canvas.width) / box.width,
          ((event.clientY - box.top) * canvas.height) / box.height,
        ].map((v) => Math.round(v * 10) / 10);
      if (kind === "target") {
        view.target = p;
        $("patch-point-help").textContent =
          "Ora clicca lo stesso punto nel candidato generato.";
      } else if (view.target) {
        view.pairs.push({ target: view.target, generated: p });
        view.target = null;
        $("patch-point-help").textContent =
          "Coppia aggiunta. Scegli altri punti stabili per verificare l’allineamento.";
      } else {
        fail("Scegli prima il punto nel contesto originale");
        return;
      }
      invalidate();
      renderPoints();
      drawImages();
    };
  $("patch-view-zoom").oninput = drawImages;
  $("patch-clear-points").onclick = () => {
    view.pairs = [];
    view.target = null;
    invalidate();
    renderPoints();
    drawImages();
  };
  for (const id of [
    "patch-mapping",
    "patch-input-scale",
    "patch-offset-x",
    "patch-offset-y",
    "patch-allow-scale",
    "patch-allow-rotation",
    "patch-nearest",
    "patch-tolerance",
    "patch-feather",
  ])
    $(id).onchange = invalidate;
  $("patch-preview").onclick = () =>
    run(async () => {
      if (!view.request || !view.candidate)
        throw new Error("Carica prima il PNG candidato");
      const key = signature(),
        result = await post("/api/patch/registration", {
          request_id: view.request.id,
          upload_id: view.candidate.id,
          registration: registration(),
        });
      if (key !== signature())
        throw new Error(
          "Parametri cambiati durante il calcolo: ripeti l’anteprima",
        );
      view.previewKey = key;
      $("patch-composite").src =
        "data:image/png;base64," + result.composite_png;
      $("patch-composite").hidden = false;
      const t = result.transform;
      $("patch-transform").textContent =
        `${t.landmark_count} landmark · residuo massimo ${t.max_residual_px.toFixed(2)} px · ${result.verification.outside_mask_changed_pixels} pixel modificati fuori maschera. ${t.landmark_count ? "Controlla visivamente attacchi e contorni." : "Allineamento geometrico ancora da verificare visivamente."}`;
      message(
        "Anteprima calcolata attraverso la maschera. Nessuna modifica al progetto finché non reinserisci.",
      );
    });
  $("patch-apply").onclick = () =>
    run(async () => {
      if (!view.request || !view.candidate || view.previewKey !== signature())
        throw new Error("Ricalcola l’anteprima con i parametri correnti");
      const generation = {
        service: $("patch-service").value,
        output_provenance: $("patch-provenance").value,
        prompt_confirmed_exact: $("patch-prompt-confirmed").checked,
        supplied_files: [
          ...$("patch-supplied-files").querySelectorAll("input:checked"),
        ].map((i) => i.value),
      };
      const result = await post("/api/patch/apply", {
        project: state.project,
        request_id: view.request.id,
        upload_id: view.candidate.id,
        registration: registration(),
        generation,
      });
      const operation =
        result.project.frames[result.attempt.frame - 1].edits.at(-1);
      await loadProject(result.project, result.attempt.frame - 1, operation.id);
      await reload();
      setAttempt(result.attempt.id);
      step("review");
      message(
        "Correzione reinserita solo nella maschera. Stato: da verificare; sorgente invariata.",
      );
    });
  $("patch-attempt").onchange = () => setAttempt($("patch-attempt").value);
  async function decide(status) {
    if (!view.attempt) throw new Error("Seleziona un tentativo da revisionare");
    const decision = {
      status,
      reviewer: $("patch-reviewer").value,
      notes: $("patch-review-notes").value,
      checks: Object.fromEntries(
        Object.keys(checks).map((k) => [k, $("patch-check-" + k).checked]),
      ),
      evidence: $("patch-review-evidence")
        .value.split("\n")
        .map((s) => s.trim())
        .filter(Boolean),
    };
    const result = await post("/api/patch/review", {
      project: state.project,
      attempt_id: view.attempt.id,
      decision,
    });
    await loadProject(result.project);
    await reload();
    setAttempt(result.attempt.id);
    message(
      status === "rejected"
        ? "Tentativo scartato e frame precedente ripristinato. Decisione e candidato conservati."
        : "Approvazione della correzione registrata. Integrazione nel gioco e merge restano separati.",
    );
  }
  $("patch-approve").onclick = () => run(() => decide("approved"));
  $("patch-reject").onclick = () => run(() => decide("rejected"));
  window.SpritePatches = { refresh };
  refresh();
  step("prepare");
})();
