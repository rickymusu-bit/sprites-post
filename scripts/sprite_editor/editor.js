"use strict";
const $ = (id) => document.getElementById(id);
const COLORS = [
  "#c4ed8c",
  "#65dcec",
  "#ffa48a",
  "#c4a5f3",
  "#ffd46e",
  "#ed94c9",
];
const LABELS = {
  shoulder_mass_center: "Spalla",
  upper_thorax: "Torace alto",
  lower_thorax: "Torace basso",
};
const state = {
  project: null,
  token: null,
  frame: 0,
  selected: null,
  names: [],
  preview: null,
  images: [],
  undo: [],
  redo: [],
  zoom: 0.85,
  fit: true,
  mode: "side",
  dirty: false,
  playing: false,
  request: 0,
  ready: false,
};
let previewTimer, playTimer, drag;
const clone = (value) => structuredClone(value);
const nice = (name) => LABELS[name] || name.replaceAll("_", " ");
function error(message) {
  $("error").textContent = message;
  $("error").hidden = !message;
}
function notice(message) {
  $("notice").textContent = message;
}
async function post(path, project = state.project) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Sprite-Token": state.token,
    },
    body: JSON.stringify(project),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Operazione non riuscita");
  return result;
}
function history() {
  state.undo.push(clone(state.project));
  if (state.undo.length > 100) state.undo.shift();
  state.redo = [];
}
function changed() {
  state.dirty = true;
  $("save-state").textContent = "Modifiche non salvate";
  controls();
  schedulePreview();
}
function edit(fn) {
  pause();
  history();
  fn();
  changed();
}
function schedulePreview() {
  clearTimeout(previewTimer);
  state.request++;
  state.ready = false;
  $("export").disabled = true;
  previewTimer = setTimeout(updatePreview, 80);
}
async function image(url) {
  const im = new Image();
  im.src = url;
  await im.decode();
  return im;
}
async function updatePreview() {
  const request = ++state.request;
  $("busy").hidden = false;
  try {
    const result = await post("/api/preview");
    const images = await Promise.all(
      result.frames.map(async (frame) => ({
        raw: await image(frame.raw_url),
        aligned: await image(frame.aligned_url),
      })),
    );
    if (request !== state.request) return;
    state.preview = result;
    state.images = images;
    state.ready = true;
    error("");
    for (const id of ["raw-canvas", "aligned-canvas"]) {
      $(id).width = result.canvas[0];
      $(id).height = result.canvas[1];
    }
    if (state.fit) fitView();
    else applyZoom();
    renderTimeline();
    controls();
    draw();
  } catch (e) {
    if (request === state.request) {
      state.ready = false;
      error(e.message);
    }
  } finally {
    if (request === state.request) $("busy").hidden = true;
  }
}
function names() {
  state.names = [
    ...new Set([
      ...(state.project.editor_point_names || []),
      ...state.project.frames.flatMap((f) => Object.keys(f.points)),
    ]),
  ];
  if (!state.names.length) state.names = ["spalla", "torace", "bacino"];
  if (!state.names.includes(state.selected)) state.selected = state.names[0];
}
function controls() {
  if (!state.project) return;
  names();
  const frame = state.project.frames[state.frame],
    p = frame.points[state.selected];
  $("frame-label").textContent =
    `FRAME ${String(state.frame + 1).padStart(2, "0")} / ${String(state.project.frames.length).padStart(2, "0")}`;
  $("reference").value = state.project.reference_frame;
  $("point-count").textContent =
    `${Object.keys(frame.points).length} / ${state.names.length}`;
  $("point-list").replaceChildren();
  state.names.forEach((name, i) => {
    const point = frame.points[name],
      button = document.createElement("button");
    button.type = "button";
    button.className =
      "point-row" +
      (name === state.selected ? " selected" : "") +
      (!point ? " missing" : "");
    button.setAttribute("aria-label", `Seleziona punto ${nice(name)}`);
    button.setAttribute("aria-pressed", String(name === state.selected));
    const swatch = document.createElement("span");
    swatch.className = "point-swatch";
    swatch.style.background = COLORS[i % COLORS.length];
    const label = document.createElement("span");
    label.className = "point-name";
    label.textContent = nice(name);
    const value = document.createElement("span");
    value.className = "point-value";
    value.textContent = point
      ? `${point.xy[0].toFixed(0)}, ${point.xy[1].toFixed(0)}`
      : "da segnare";
    button.append(swatch, label, value);
    button.onclick = () => {
      state.selected = name;
      controls();
      draw();
    };
    $("point-list").append(button);
  });
  $("selected-label").textContent = nice(state.selected).toUpperCase();
  $("point-x").value = p ? p.xy[0].toFixed(1) : "";
  $("point-y").value = p ? p.xy[1].toFixed(1) : "";
  $("point-weight").value = p ? p.weight : 1;
  $("remove-point").disabled = !p;
  $("point-help").textContent = p
    ? "Trascina il punto sull’originale o modifica le coordinate."
    : "Clicca sull’originale per segnare questo punto. Non vengono inventate posizioni.";
  $("motion-x").value = frame.motion[0];
  $("motion-y").value = frame.motion[1];
  $("allow-scale").checked = state.project.allow_scale;
  $("align-body").checked = state.project.align_body !== false;
  $("nearest").checked = state.project.nearest;
  $("duration").value = state.project.duration_ms;
  $("undo").disabled = !state.undo.length;
  $("redo").disabled = !state.redo.length;
  $("export").disabled = !state.ready || !state.preview?.can_export;
  if (state.preview) {
    const check = state.preview.frames[state.frame].check;
    $("fit-state").textContent =
      check.status === "disabled"
        ? "Correzioni locali"
        : check.status === "fitted"
          ? "Punti allineati"
          : check.status === "missing"
            ? "Punti mancanti"
            : "Allineamento provvisorio";
    $("fit-state").classList.toggle("provisional", check.status !== "fitted");
    $("fit-message").textContent =
      check.message ||
      `${check.landmark_count} punti in comune · verifica visivamente proporzioni e movimento`;
    $("residual").textContent = Number.isFinite(check.weighted_rms_px)
      ? `RMS ${check.weighted_rms_px.toFixed(1)} px`
      : "—";
    $("canvas-size").textContent = state.preview.canvas.join(" × ") + " px";
  }
  $("source-box").textContent = `[${frame.source_box.join(", ")}]`;
  [...$("timeline").children].forEach((button, i) => {
    button.classList.toggle("active", i === state.frame);
    button.setAttribute("aria-current", i === state.frame ? "true" : "false");
  });
  window.SpriteLocal?.refresh();
  window.SpritePatches?.refresh();
}
function renderTimeline() {
  $("timeline").replaceChildren();
  state.project.frames.forEach((_, i) => {
    const button = document.createElement("button");
    button.className = "thumb";
    button.setAttribute("aria-label", `Mostra frame ${i + 1}`);
    const img = document.createElement("img");
    img.src = state.preview.frames[i].aligned_url;
    img.alt = "";
    const label = document.createElement("span");
    label.textContent = String(i + 1).padStart(2, "0");
    button.append(img, label);
    if (i === state.project.reference_frame - 1) {
      const mark = document.createElement("span");
      mark.className = "reference-mark";
      mark.textContent = "◆ REF";
      button.append(mark);
    }
    button.onclick = () => {
      pause();
      select(i);
    };
    $("timeline").append(button);
  });
}
function transform(xy, m) {
  return [
    m[0] * xy[0] + m[2] * xy[1] + m[4],
    m[1] * xy[0] + m[3] * xy[1] + m[5],
  ];
}
function pointMarkers(ctx, matrix) {
  const frame = state.project.frames[state.frame];
  state.names.forEach((name, i) => {
    const p = frame.points[name];
    if (!p) return;
    const [x, y] = transform(p.xy, matrix),
      color = COLORS[i % COLORS.length],
      radius = (name === state.selected ? 6 : 4) / state.zoom;
    ctx.save();
    ctx.lineWidth = 2 / state.zoom;
    ctx.strokeStyle = color;
    ctx.fillStyle = "#14181ed9";
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x - radius - 4 / state.zoom, y);
    ctx.lineTo(x + radius + 4 / state.zoom, y);
    ctx.moveTo(x, y - radius - 4 / state.zoom);
    ctx.lineTo(x, y + radius + 4 / state.zoom);
    ctx.stroke();
    if (name === state.selected) {
      ctx.font = `${11 / state.zoom}px system-ui`;
      const label = nice(name);
      const width = ctx.measureText(label).width;
      ctx.fillStyle = "#10151ddd";
      ctx.fillRect(
        x + 10 / state.zoom,
        y - 22 / state.zoom,
        width + 12 / state.zoom,
        20 / state.zoom,
      );
      ctx.fillStyle = color;
      ctx.fillText(label, x + 16 / state.zoom, y - 8 / state.zoom);
    }
    ctx.restore();
  });
}
function ghost(ctx, img, color, alpha) {
  const buffer = document.createElement("canvas");
  buffer.width = img.width;
  buffer.height = img.height;
  const c = buffer.getContext("2d");
  c.drawImage(img, 0, 0);
  c.globalCompositeOperation = "source-in";
  c.fillStyle = color;
  c.fillRect(0, 0, buffer.width, buffer.height);
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.drawImage(buffer, 0, 0);
  ctx.restore();
}
function draw() {
  if (!state.ready) return;
  const raw = $("raw-canvas").getContext("2d"),
    aligned = $("aligned-canvas").getContext("2d"),
    current = state.images[state.frame];
  raw.clearRect(0, 0, raw.canvas.width, raw.canvas.height);
  aligned.clearRect(0, 0, aligned.canvas.width, aligned.canvas.height);
  raw.imageSmoothingEnabled = aligned.imageSmoothingEnabled =
    !state.project.nearest;
  raw.drawImage(current.raw, 0, 0);
  pointMarkers(raw, state.preview.frames[state.frame].raw_matrix);
  aligned.drawImage(current.aligned, 0, 0);
  const opacity = Number($("opacity").value);
  if (state.mode === "overlay") {
    ghost(aligned, current.raw, "#ff7c83", opacity);
    ghost(aligned, current.aligned, "#64d9ed", opacity);
  }
  if ($("show-onion").checked) {
    const total = state.images.length;
    ghost(
      aligned,
      state.images[(state.frame + total - 1) % total].aligned,
      "#ff7c83",
      opacity,
    );
    ghost(
      aligned,
      state.images[(state.frame + 1) % total].aligned,
      "#64d9ed",
      opacity,
    );
  }
  if (state.project.align_body !== false)
    pointMarkers(aligned, state.preview.frames[state.frame].aligned_matrix);
  $("aligned-title").textContent =
    state.mode === "overlay"
      ? "Sovrapposizione prima / dopo"
      : state.project.align_body === false
        ? "Corretto · anteprima"
        : "Allineato · anteprima";
  $("onion-legend").textContent = $("show-onion").checked
    ? "Rosso: precedente · ciano: successivo"
    : state.mode === "overlay"
      ? "Rosso: originale · ciano: allineato"
      : "Stesso canvas dell’esportazione";
  window.SpriteLocal?.draw(raw);
}
function select(index) {
  state.frame =
    (index + state.project.frames.length) % state.project.frames.length;
  controls();
  draw();
}
function applyZoom() {
  for (const id of ["raw-canvas", "aligned-canvas"]) {
    const canvas = $(id);
    canvas.style.width = canvas.width * state.zoom + "px";
    canvas.style.height = canvas.height * state.zoom + "px";
  }
  $("zoom").value = Math.round(state.zoom * 100);
  $("zoom-value").textContent = Math.round(state.zoom * 100) + "%";
  draw();
}
function fitView() {
  const view = $("raw-viewport");
  state.zoom = Math.max(
    0.25,
    Math.min(
      2.5,
      (view.clientWidth - 28) / $("raw-canvas").width,
      (view.clientHeight - 25) / $("raw-canvas").height,
    ),
  );
  applyZoom();
}
function pause() {
  clearInterval(playTimer);
  state.playing = false;
  $("play").textContent = "▶";
  $("play").setAttribute("aria-label", "Riproduci animazione");
}
function play() {
  if (!state.ready) return;
  pause();
  state.playing = true;
  $("play").textContent = "Ⅱ";
  $("play").setAttribute("aria-label", "Ferma animazione");
  playTimer = setInterval(
    () => select(state.frame + 1),
    state.project.duration_ms / Number($("speed").value),
  );
}
function localPoint(event, clamp = true) {
  const canvas = $("raw-canvas"),
    rect = canvas.getBoundingClientRect(),
    m = state.preview.frames[state.frame].raw_matrix;
  const x = ((event.clientX - rect.left) * canvas.width) / rect.width,
    y = ((event.clientY - rect.top) * canvas.height) / rect.height;
  const box = state.project.frames[state.frame].source_box;
  if (!clamp)
    return [(x - m[4]) / m[0], (y - m[5]) / m[3]].map(
      (v) => Math.round(v * 10) / 10,
    );
  return [
    Math.max(box[0], Math.min(box[2] - 0.1, (x - m[4]) / m[0])),
    Math.max(box[1], Math.min(box[3] - 0.1, (y - m[5]) / m[3])),
  ].map((v) => Math.round(v * 10) / 10);
}
$("raw-canvas").addEventListener("pointerdown", (event) => {
  if (window.SpriteLocal?.active()) return window.SpriteLocal.down(event);
  if (!state.ready || event.button !== 0) return;
  pause();
  const xy = localPoint(event),
    frame = state.project.frames[state.frame];
  let best = null,
    distance = 14 / state.zoom;
  for (const [name, p] of Object.entries(frame.points)) {
    const d = Math.hypot(p.xy[0] - xy[0], p.xy[1] - xy[1]);
    if (d < distance) {
      best = name;
      distance = d;
    }
  }
  if (best) state.selected = best;
  drag = {
    project: clone(state.project),
    pointer: event.pointerId,
    name: state.selected,
  };
  $("raw-canvas").setPointerCapture(event.pointerId);
  if (!best) {
    frame.points[state.selected] = { xy, weight: 1 };
    controls();
    draw();
  }
});
$("raw-canvas").addEventListener("pointermove", (event) => {
  if (window.SpriteLocal?.active()) return window.SpriteLocal.move(event);
  if (!drag) return;
  const old = state.project.frames[state.frame].points[drag.name];
  state.project.frames[state.frame].points[drag.name] = {
    xy: localPoint(event),
    weight: old?.weight || 1,
  };
  controls();
  draw();
});
function endDrag(event) {
  if (window.SpriteLocal?.active()) return window.SpriteLocal.up(event);
  if (!drag) return;
  const before = drag.project;
  drag = null;
  if ($("raw-canvas").hasPointerCapture(event.pointerId))
    $("raw-canvas").releasePointerCapture(event.pointerId);
  if (JSON.stringify(before) !== JSON.stringify(state.project)) {
    state.undo.push(before);
    if (state.undo.length > 100) state.undo.shift();
    state.redo = [];
    changed();
  }
}
$("raw-canvas").addEventListener("pointerup", endDrag);
$("raw-canvas").addEventListener("pointercancel", endDrag);
$("add-point").onsubmit = (event) => {
  event.preventDefault();
  const name = $("point-name").value.trim();
  if (!name) return;
  edit(() => {
    state.project.editor_point_names = [...new Set([...state.names, name])];
    state.selected = name;
    $("point-name").value = "";
  });
};
for (const [id, axis] of [
  ["point-x", 0],
  ["point-y", 1],
])
  $(id).onchange = () => {
    const entry = state.project.frames[state.frame],
      p = entry.points[state.selected];
    if (!p) return;
    const value = Number($(id).value),
      box = entry.source_box;
    if (
      !Number.isFinite(value) ||
      value < box[axis] ||
      value >= box[axis + 2]
    ) {
      error("Coordinate fuori dal ritaglio del frame");
      controls();
      return;
    }
    edit(() => {
      p.xy[axis] = value;
    });
  };
$("point-weight").onchange = () => {
  const p = state.project.frames[state.frame].points[state.selected],
    value = Number($("point-weight").value);
  if (!p) return;
  if (!Number.isFinite(value) || value <= 0) {
    error("L’affidabilità deve essere positiva");
    controls();
    return;
  }
  edit(() => {
    p.weight = value;
  });
};
$("remove-point").onclick = () =>
  edit(() => delete state.project.frames[state.frame].points[state.selected]);
$("reference").onchange = () =>
  edit(() => {
    state.project.reference_frame = Number($("reference").value);
  });
$("align-body").onchange = () =>
  edit(() => {
    state.project.align_body = $("align-body").checked;
  });
for (const [id, axis] of [
  ["motion-x", 0],
  ["motion-y", 1],
])
  $(id).onchange = () => {
    const value = Number($(id).value);
    if (Number.isFinite(value))
      edit(() => {
        state.project.frames[state.frame].motion[axis] = value;
      });
  };
for (const [id, key] of [
  ["allow-scale", "allow_scale"],
  ["nearest", "nearest"],
])
  $(id).onchange = () =>
    edit(() => {
      state.project[key] = $(id).checked;
    });
$("duration").onchange = () => {
  const value = Number($("duration").value);
  if (!Number.isInteger(value) || value < 10 || value > 60000 || value % 10) {
    error("Durata: usa un multiplo di 10 ms");
    controls();
    return;
  }
  edit(() => {
    state.project.duration_ms = value;
  });
};
$("undo").onclick = () => {
  if (!state.undo.length) return;
  pause();
  state.redo.push(clone(state.project));
  state.project = state.undo.pop();
  changed();
};
$("redo").onclick = () => {
  if (!state.redo.length) return;
  pause();
  state.undo.push(clone(state.project));
  state.project = state.redo.pop();
  changed();
};
$("previous").onclick = () => {
  pause();
  select(state.frame - 1);
};
$("next").onclick = () => {
  pause();
  select(state.frame + 1);
};
$("play").onclick = () => (state.playing ? pause() : play());
$("speed").onchange = () => {
  if (state.playing) play();
};
$("side-mode").onclick = () => mode("side");
$("overlay-mode").onclick = () => mode("overlay");
function mode(value) {
  state.mode = value;
  for (const [id, name] of [
    ["side-mode", "side"],
    ["overlay-mode", "overlay"],
  ]) {
    $(id).classList.toggle("active", value === name);
    $(id).setAttribute("aria-pressed", String(value === name));
  }
  draw();
}
$("show-onion").onchange = draw;
$("opacity").oninput = () => {
  $("opacity-value").textContent =
    Math.round(Number($("opacity").value) * 100) + "%";
  draw();
};
$("zoom").oninput = () => {
  state.fit = false;
  state.zoom = Number($("zoom").value) / 100;
  applyZoom();
};
$("fit").onclick = () => {
  state.fit = true;
  fitView();
};
$("save-project").onclick = async () => {
  try {
    const snapshot = JSON.stringify(state.project);
    const result = await post("/api/save");
    if (JSON.stringify(state.project) === snapshot) {
      state.dirty = false;
      $("save-state").textContent = "Progetto salvato";
    }
    notice(`Salvato localmente: ${result.path}`);
    error("");
  } catch (e) {
    error(e.message);
  }
};
$("export").onclick = async () => {
  if (!state.ready || !state.preview.can_export) return;
  pause();
  $("export").disabled = true;
  notice("Esportazione locale in corso…");
  try {
    const result = await post("/api/export");
    notice(`PNG, GIF e dati di allineamento salvati in ${result.path}`);
    error("");
  } catch (e) {
    error(e.message);
  } finally {
    controls();
  }
};
$("load-project").onclick = () => $("project-file").click();
$("project-file").onchange = async () => {
  const file = $("project-file").files[0];
  if (!file) return;
  try {
    const project = JSON.parse(await file.text());
    const validated = await post("/api/preview", project);
    history();
    state.project = validated.project;
    state.selected = null;
    changed();
    notice(`Progetto aperto: ${file.name}`);
  } catch (e) {
    error(e.message);
  } finally {
    $("project-file").value = "";
  }
};
document.addEventListener("keydown", (event) => {
  if ($("patch-dialog")?.open) return;
  const input = ["INPUT", "SELECT", "TEXTAREA"].includes(
    document.activeElement.tagName,
  );
  if (input) return;
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
    event.preventDefault();
    $(event.shiftKey ? "redo" : "undo").click();
  } else if (event.key === "ArrowLeft") {
    event.preventDefault();
    $("previous").click();
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    $("next").click();
  } else if (event.code === "Space") {
    event.preventDefault();
    $("play").click();
  }
});
window.addEventListener("beforeunload", (event) => {
  if (state.dirty) {
    event.preventDefault();
    event.returnValue = "";
  }
});
window.addEventListener("resize", () => {
  if (state.ready && state.fit) fitView();
});
(async () => {
  try {
    const response = await fetch("/api/state");
    const initial = await response.json();
    state.project = initial.project;
    state.token = initial.token;
    $("source-name").textContent =
      `${initial.source_name} · ${initial.frame_count} pose · ${initial.source_size.join(" × ")} px`;
    $("output-path").textContent = initial.output;
    initial.project.frames.forEach((_, i) => {
      const option = document.createElement("option");
      option.value = i + 1;
      option.textContent = `Frame ${String(i + 1).padStart(2, "0")}`;
      $("reference").append(option);
    });
    controls();
    await updatePreview();
  } catch (e) {
    error(e.message);
  }
})();
