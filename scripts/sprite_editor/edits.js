"use strict";

// Input gestures only record recipes. The deterministic Python renderer makes
// every edited pixel; Canvas overlays here are selection/pivot guides only.
(() => {
  const local = {
    active: false,
    tool: "polygon",
    polygon: [],
    selected: null,
    frame: -1,
    origins: {},
    gesture: null,
  };
  const entry = () => state.project.frames[state.frame];
  const operations = () => entry().edits || (entry().edits = []);
  const selected = () => operations().find((op) => op.id === local.selected);
  const setHidden = (id, hidden) => {
    $(id).hidden = hidden;
  };

  function mode(active) {
    pause();
    local.active = active;
    local.polygon = [];
    $("landmark-panel").hidden = active;
    $("local-panel").hidden = !active;
    for (const [id, value] of [
      ["landmark-mode", !active],
      ["local-mode", active],
    ]) {
      $(id).classList.toggle("active", value);
      $(id).setAttribute("aria-pressed", String(value));
    }
    refresh();
    draw();
  }

  function tool(name) {
    pause();
    local.tool = name;
    local.polygon = [];
    if (["polygon", "paint", "erase", "clone"].includes(name))
      local.selected = null;
    refresh();
    draw();
  }

  function refresh() {
    if (!state.project) return;
    $("raw-title").textContent = local.active
      ? "Originale · maschere e campioni"
      : "Originale · modifica i punti";
    $("workspace-heading").textContent = local.active
      ? "Correggi i frame. Conserva l’originale."
      : "Allinea i punti. Controlla il movimento.";
    if (local.frame !== state.frame) {
      local.frame = state.frame;
      local.polygon = [];
      local.selected = null;
      local.gesture = null;
    }
    const edits = operations(),
      op = selected();
    $("edit-count").textContent = edits.length;
    $("edit-list").replaceChildren();
    edits.forEach((operation, i) => {
      const row = document.createElement("div");
      row.className =
        "edit-row" + (operation.id === local.selected ? " selected" : "");
      const enabled = document.createElement("input");
      enabled.type = "checkbox";
      enabled.checked = operation.enabled !== false;
      enabled.setAttribute("aria-label", `Attiva ${operation.name}`);
      enabled.onchange = () =>
        edit(() => {
          operation.enabled = enabled.checked;
        });
      const button = document.createElement("button");
      const status = state.preview?.frames[state.frame]?.edit_operations.find(
        (r) => r.id === operation.id,
      )?.review?.status;
      const statusLabel = {
        approved: "approvata",
        rejected: "scartata",
        pending_visual_review: "da verificare",
        unavailable: "revisione non disponibile",
      }[status];
      button.textContent =
        operation.name +
        (operation.type === "patch" && statusLabel ? ` · ${statusLabel}` : "");
      button.title = operation.type;
      button.setAttribute("aria-label", `Modifica ${operation.name}`);
      button.onclick = () => {
        local.selected = operation.id;
        local.tool = operation.type === "part" ? "select" : operation.type;
        refresh();
        draw();
      };
      const count = document.createElement("span");
      count.textContent = String(i + 1).padStart(2, "0");
      row.append(enabled, button, count);
      $("edit-list").append(row);
    });
    if (!edits.length) {
      const empty = document.createElement("p");
      empty.className = "hint";
      empty.textContent = "Nessuna correzione in questo frame.";
      $("edit-list").append(empty);
    }
    const isPart =
      op?.type === "part" && ["select", "pivot"].includes(local.tool);
    setHidden("part-controls", !isPart);
    setHidden(
      "brush-controls",
      !["paint", "erase", "clone", "clone-source", "pick"].includes(local.tool),
    );
    setHidden("paint-controls", !["paint", "pick"].includes(local.tool));
    setHidden(
      "clone-controls",
      !["clone", "clone-source"].includes(local.tool),
    );
    setHidden("mask-actions", local.tool !== "polygon");
    $("finish-mask").disabled = local.polygon.length < 3;
    $("remove-edit").disabled = !op;
    const index = edits.indexOf(op);
    $("edit-earlier").disabled = index <= 0;
    $("edit-later").disabled = index < 0 || index === edits.length - 1;
    for (const [id, t] of [
      ["tool-part", "polygon"],
      ["tool-paint", "paint"],
      ["tool-erase", "erase"],
      ["tool-clone", "clone"],
    ]) {
      const active =
        local.tool === t ||
        (t === "polygon" && ["select", "pivot"].includes(local.tool)) ||
        (t === "clone" && local.tool === "clone-source") ||
        (t === "paint" && local.tool === "pick");
      $(id).classList.toggle("active", active);
      $(id).setAttribute("aria-pressed", String(active));
    }
    if (isPart) {
      $("part-name").value = op.name;
      $("pivot-x").value = op.pivot[0];
      $("pivot-y").value = op.pivot[1];
      $("part-x").value = op.translate[0];
      $("part-y").value = op.translate[1];
      $("part-angle").value = op.rotation_deg;
      $("part-scale").value = op.scale;
      $("part-cut").checked = op.cut;
      $("part-angle").disabled = $("part-scale").disabled = !op.pivot_confirmed;
      $("pivot-status").textContent = op.pivot_confirmed
        ? "Pivot scelto. Controlla sempre l’attacco fra i segmenti."
        : "Clicca sull’articolazione per scegliere il pivot prima della rotazione.";
    }
    if (op && ["paint", "erase", "clone"].includes(op.type)) {
      $("brush-radius").value = op.radius;
      if (op.type === "paint")
        $("paint-color").value =
          "#" +
          op.color
            .slice(0, 3)
            .map((v) => v.toString(16).padStart(2, "0"))
            .join("");
    }
    const origin = local.origins[state.frame];
    $("clone-origin").textContent = origin
      ? `Origine nel frame ${state.frame + 1}: ${origin.join(", ")}`
      : "Scegli un campione visibile nell’originale.";
    const help = {
      patch:
        "Correzione esterna mascherata: attiva/disattiva per confrontare. Per cambiarla prepara un nuovo intervento.",
      polygon: `Clicca i vertici sull’originale (${local.polygon.length}), poi chiudi la maschera.`,
      select:
        "Trascina dentro la selezione per spostare la parte; usa i campi per ruotarla.",
      pivot: "Clicca o trascina il pivot sull’articolazione visibile.",
      paint:
        "Trascina sull’originale per registrare un tratto. Il risultato appare a destra.",
      erase:
        "Trascina per cancellare nel risultato; l’originale resta intatto.",
      clone: origin
        ? "Trascina sulla zona da ricostruire; il campione proviene dall’originale."
        : "Prima imposta l’origine del clone.",
      "clone-source": "Clicca la zona originale da usare come campione.",
      pick: "Clicca un pixel dell’originale per campionare il colore.",
    };
    $("local-help").textContent = help[local.tool] || help.polygon;
  }

  function partMatrix(op) {
    const angle = (op.rotation_deg * Math.PI) / 180,
      a = op.scale * Math.cos(angle),
      b = op.scale * Math.sin(angle),
      [x, y] = op.pivot;
    return [
      a,
      b,
      -b,
      a,
      x + op.translate[0] - a * x + b * y,
      y + op.translate[1] - b * x - a * y,
    ];
  }

  function guide(ctx, points, color, dashed = false, close = true) {
    if (!points.length) return;
    const m = state.preview.frames[state.frame].raw_matrix;
    ctx.save();
    ctx.lineWidth = 1.5 / state.zoom;
    ctx.strokeStyle = color;
    ctx.fillStyle = color + "22";
    if (dashed) ctx.setLineDash([5 / state.zoom, 4 / state.zoom]);
    ctx.beginPath();
    points.forEach((p, i) => {
      const [x, y] = transform(p, m);
      if (i) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
    });
    if (close) {
      ctx.closePath();
      ctx.fill();
    }
    ctx.stroke();
    ctx.restore();
  }

  function cross(ctx, point, color, label) {
    const [x, y] = transform(
        point,
        state.preview.frames[state.frame].raw_matrix,
      ),
      r = 8 / state.zoom;
    ctx.save();
    ctx.lineWidth = 2 / state.zoom;
    ctx.strokeStyle = color;
    ctx.beginPath();
    ctx.arc(x, y, r * 0.6, 0, Math.PI * 2);
    ctx.moveTo(x - r, y);
    ctx.lineTo(x + r, y);
    ctx.moveTo(x, y - r);
    ctx.lineTo(x, y + r);
    ctx.stroke();
    if (label) {
      ctx.font = `${11 / state.zoom}px system-ui`;
      ctx.fillStyle = color;
      ctx.fillText(label, x + 12 / state.zoom, y - 8 / state.zoom);
    }
    ctx.restore();
  }

  function drawLocal(ctx) {
    if (!local.active || !state.preview) return;
    const op = selected();
    if (op?.type === "part") {
      guide(ctx, op.mask, "#65dcec");
      const m = partMatrix(op);
      guide(
        ctx,
        op.mask.map((p) => transform(p, m)),
        "#c4ed8c",
        true,
      );
      cross(
        ctx,
        op.pivot,
        op.pivot_confirmed ? "#ffd46e" : "#ff7c83",
        op.pivot_confirmed ? "Pivot" : "Scegli pivot",
      );
    }
    if (op?.type === "patch") {
      if (op.mask_outline) guide(ctx, op.mask_outline, "#65dcec");
      const [l, t, r, b] = op.crop_box;
      guide(
        ctx,
        [
          [l, t],
          [r, t],
          [r, b],
          [l, b],
        ],
        "#ffd46e",
        true,
      );
    }
    if (local.polygon.length)
      guide(ctx, local.polygon, "#c4ed8c", false, false);
    const origin = local.origins[state.frame];
    if (origin && ["clone", "clone-source"].includes(local.tool))
      cross(ctx, origin, "#ffd46e", "Origine clone");
    if (local.gesture?.kind === "brush")
      guide(ctx, local.gesture.operation.points, "#c4ed8c", false, false);
  }

  function inside(point, polygon) {
    let yes = false;
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
      const a = polygon[i],
        b = polygon[j];
      if (
        a[1] > point[1] !== b[1] > point[1] &&
        point[0] < ((b[0] - a[0]) * (point[1] - a[1])) / (b[1] - a[1]) + a[0]
      )
        yes = !yes;
    }
    return yes;
  }

  function down(event) {
    if (!state.ready || event.button !== 0) return;
    pause();
    const xy = localPoint(event, false),
      op = selected();
    if (local.tool === "polygon") {
      local.polygon.push(xy);
      refresh();
      draw();
      return;
    }
    if (local.tool === "pick") {
      const m = state.preview.frames[state.frame].raw_matrix,
        [x, y] = transform(xy, m),
        im = state.images[state.frame].raw;
      const c = document.createElement("canvas");
      c.width = im.width;
      c.height = im.height;
      const ctx = c.getContext("2d");
      ctx.drawImage(im, 0, 0);
      const p = ctx.getImageData(Math.floor(x), Math.floor(y), 1, 1).data;
      if (!p[3]) {
        notice("Qui non ci sono pixel visibili da campionare.");
        return;
      }
      $("paint-color").value =
        "#" +
        [...p]
          .slice(0, 3)
          .map((v) => v.toString(16).padStart(2, "0"))
          .join("");
      tool("paint");
      return;
    }
    if (local.tool === "clone-source") {
      local.origins[state.frame] = xy;
      if (op?.type === "clone")
        edit(() => {
          op.source_point = xy;
          op.source_frame = state.frame;
        });
      local.tool = "clone";
      refresh();
      draw();
      return;
    }
    if (["select", "pivot"].includes(local.tool) && op?.type === "part") {
      const kind = local.tool === "pivot" ? "pivot" : "translate";
      if (kind === "translate" && !inside(xy, op.mask)) {
        notice("Trascina dentro la maschera selezionata.");
        return;
      }
      local.gesture = {
        kind,
        start: xy,
        before: clone(state.project),
        id: op.id,
        translate: [...op.translate],
      };
      if (kind === "pivot") {
        op.pivot = xy;
        op.pivot_confirmed = true;
      }
    } else if (["paint", "erase", "clone"].includes(local.tool)) {
      const radius = Number($("brush-radius").value);
      if (!Number.isFinite(radius) || radius < 0.5 || radius > 256) {
        error("Raggio del pennello non valido");
        return;
      }
      if (local.tool === "clone" && !local.origins[state.frame]) {
        tool("clone-source");
        notice("Scegli prima il campione nell’originale.");
        return;
      }
      const operation = {
        id: crypto.randomUUID(),
        name:
          { paint: "Pennello", erase: "Gomma", clone: "Clone" }[local.tool] +
          " " +
          (operations().length + 1),
        type: local.tool,
        enabled: true,
        points: [xy],
        radius,
      };
      if (local.tool === "paint")
        operation.color = [
          $("paint-color").value.slice(1, 3),
          $("paint-color").value.slice(3, 5),
          $("paint-color").value.slice(5, 7),
        ]
          .map((v) => parseInt(v, 16))
          .concat(255);
      if (local.tool === "clone") {
        operation.source_frame = state.frame;
        operation.source_point = [...local.origins[state.frame]];
      }
      local.gesture = {
        kind: "brush",
        before: clone(state.project),
        operation,
      };
    } else return;
    $("raw-canvas").setPointerCapture(event.pointerId);
    refresh();
    draw();
  }

  function move(event) {
    const gesture = local.gesture;
    if (!gesture) return;
    const xy = localPoint(event, false);
    if (gesture.kind === "brush") {
      const points = gesture.operation.points;
      if (
        Math.hypot(xy[0] - points.at(-1)[0], xy[1] - points.at(-1)[1]) >= 0.5 &&
        points.length < 4096
      )
        points.push(xy);
    } else {
      const op = operations().find((o) => o.id === gesture.id);
      if (gesture.kind === "pivot") {
        op.pivot = xy;
        op.pivot_confirmed = true;
      } else
        op.translate = gesture.translate.map(
          (v, i) => Math.round((v + xy[i] - gesture.start[i]) * 10) / 10,
        );
    }
    refresh();
    draw();
  }

  function up(event) {
    const gesture = local.gesture;
    if (!gesture) return;
    local.gesture = null;
    if ($("raw-canvas").hasPointerCapture(event.pointerId))
      $("raw-canvas").releasePointerCapture(event.pointerId);
    if (event.type === "pointercancel") {
      state.project = gesture.before;
      refresh();
      draw();
      return;
    }
    if (gesture.kind === "brush") {
      operations().push(gesture.operation);
      local.selected = gesture.operation.id;
    }
    if (JSON.stringify(gesture.before) !== JSON.stringify(state.project)) {
      state.undo.push(gesture.before);
      if (state.undo.length > 100) state.undo.shift();
      state.redo = [];
      changed();
    } else {
      refresh();
      draw();
    }
  }

  $("landmark-mode").onclick = () => mode(false);
  $("local-mode").onclick = () => mode(true);
  for (const [id, name] of [
    ["tool-part", "polygon"],
    ["tool-paint", "paint"],
    ["tool-erase", "erase"],
    ["tool-clone", "clone"],
    ["tool-pick", "pick"],
    ["tool-clone-source", "clone-source"],
  ])
    $(id).onclick = () => tool(name);
  $("tool-pivot").onclick = () => tool("pivot");
  $("finish-mask").onclick = () => {
    if (local.polygon.length < 3) return;
    const mask = clone(local.polygon),
      center = [0, 1].map(
        (axis) => mask.reduce((s, p) => s + p[axis], 0) / mask.length,
      );
    const op = {
      id: crypto.randomUUID(),
      type: "part",
      name: "Parte " + (operations().length + 1),
      enabled: true,
      mask,
      pivot: center,
      pivot_confirmed: false,
      translate: [0, 0],
      rotation_deg: 0,
      scale: 1,
      cut: true,
    };
    edit(() => {
      operations().push(op);
      local.selected = op.id;
      local.tool = "pivot";
      local.polygon = [];
    });
  };
  $("cancel-mask").onclick = () => {
    local.polygon = [];
    refresh();
    draw();
  };
  for (const [id, key, axis] of [
    ["pivot-x", "pivot", 0],
    ["pivot-y", "pivot", 1],
    ["part-x", "translate", 0],
    ["part-y", "translate", 1],
  ])
    $(id).onchange = () => {
      const value = Number($(id).value),
        op = selected();
      if (!op || !Number.isFinite(value)) return;
      edit(() => {
        op[key][axis] = value;
        if (key === "pivot") op.pivot_confirmed = true;
      });
    };
  for (const [id, key] of [
    ["part-angle", "rotation_deg"],
    ["part-scale", "scale"],
  ])
    $(id).onchange = () => {
      const op = selected(),
        value = Number($(id).value);
      if (!op || !Number.isFinite(value)) return;
      if (
        (key === "rotation_deg" && (value < -360 || value > 360)) ||
        (key === "scale" && (value < 0.1 || value > 8))
      ) {
        error("Valore della trasformazione non valido");
        refresh();
        return;
      }
      edit(() => {
        op[key] = value;
      });
    };
  $("part-name").onchange = () => {
    const op = selected(),
      name = $("part-name").value.trim();
    if (op && name)
      edit(() => {
        op.name = name;
      });
  };
  $("part-cut").onchange = () => {
    const op = selected();
    if (op)
      edit(() => {
        op.cut = $("part-cut").checked;
      });
  };
  $("brush-radius").onchange = () => {
    const op = selected(),
      radius = Number($("brush-radius").value);
    if (!Number.isFinite(radius) || radius < 0.5 || radius > 256) {
      error("Raggio del pennello non valido");
      return;
    }
    if (op && ["paint", "erase", "clone"].includes(op.type))
      edit(() => {
        op.radius = radius;
      });
  };
  $("paint-color").onchange = () => {
    const op = selected();
    if (op?.type === "paint")
      edit(() => {
        op.color = [
          $("paint-color").value.slice(1, 3),
          $("paint-color").value.slice(3, 5),
          $("paint-color").value.slice(5, 7),
        ]
          .map((v) => parseInt(v, 16))
          .concat(op.color[3]);
      });
  };
  $("remove-edit").onclick = () => {
    const op = selected();
    if (op)
      edit(() => {
        entry().edits = operations().filter((e) => e.id !== op.id);
        local.selected = null;
      });
  };
  for (const [id, direction] of [
    ["edit-earlier", -1],
    ["edit-later", 1],
  ])
    $(id).onclick = () => {
      const index = operations().indexOf(selected()),
        target = index + direction;
      if (index < 0 || target < 0 || target >= operations().length) return;
      edit(() => {
        const ops = operations();
        [ops[index], ops[target]] = [ops[target], ops[index]];
      });
    };
  window.SpriteLocal = {
    active: () => local.active,
    selection: () => (selected() ? clone(selected()) : null),
    selectOperation: (id) => {
      local.selected = id;
      local.tool = "patch";
      local.frame = state.frame;
      mode(true);
    },
    refresh,
    draw: drawLocal,
    down,
    move,
    up,
  };
})();
