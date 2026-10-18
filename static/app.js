"use strict";
const $ = id => document.getElementById(id);
let token = "", currentId = null, working = null, metadata = null, dirty = false;
let saveTask = null, saveTimer = null, selectedFile = null, selectedInbox = "", processing = false;
let switchTask = Promise.resolve();
const PAGE_SIZE = 60;
let activeSegment = -1, pageIndex = 0, matchingIndices = [], clipEnd = null, clipTimer = null;
function preference(key, value) { try { if (value === undefined) return localStorage.getItem(`localasr.${key}`); localStorage.setItem(`localasr.${key}`, String(value)); } catch (_) {} }
function statusLabel(status) { return ({DRAFT:"BROUILLON", VALIDATED:"TRANSCRIPTION VALIDÉE", QUEUED:"EN ATTENTE", TRANSCRIBING:"TRANSCRIPTION EN COURS", ERROR:"ERREUR"})[status] || status; }
function displayStatus() { $("status").textContent = `${metadata?.test ? "TEST · " : ""}${statusLabel(dirty ? "DRAFT" : metadata?.status || "DRAFT")}`; }

function showError(error) { $("error").textContent = error.message || "L’opération a échoué."; $("error").hidden = false; }
function clearError() { $("error").hidden = true; }
async function api(path, payload) {
  const response = await fetch(path, payload === undefined ? {} : {method:"POST", headers:{"Content-Type":"application/json", "X-LocalASR-Token":token}, body:JSON.stringify(payload)});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || "L’opération locale a échoué.");
  return value;
}
function timecode(value) { const ms = Math.round(value * 1000); return `${String(Math.floor(ms/3600000)).padStart(2,"0")}:${String(Math.floor(ms/60000)%60).padStart(2,"0")}:${String(Math.floor(ms/1000)%60).padStart(2,"0")}.${String(ms%1000).padStart(3,"0")}`; }
function changed() {
  dirty = true; $("saveState").textContent = "Modifications en attente…"; displayStatus();
  clearTimeout(saveTimer); saveTimer = setTimeout(() => flush().catch(showError), 700);
}
async function flush() {
  clearTimeout(saveTimer);
  if (saveTask) { await saveTask; if (dirty) return flush(); return; }
  if (!dirty || !working) return;
  saveTask = (async () => {
    while (dirty) {
      const payload = structuredClone(working); dirty = false;
      $("saveState").textContent = "Enregistrement…";
      try { const saved = await api(`/api/projects/${currentId}/save`, payload); working.revision = saved.revision; metadata.status = "DRAFT"; displayStatus(); }
      catch (error) { dirty = true; $("saveState").textContent = "Non enregistré"; throw error; }
    }
    $("saveState").textContent = "Enregistré";
  })();
  try { await saveTask; } finally { saveTask = null; }
}
function renderSegments() {
  const list = $("segments"); list.replaceChildren();
  const query = $("search").value.toLocaleLowerCase("fr");
  matchingIndices = working.segments.flatMap((segment, index) => !query || segment.text.toLocaleLowerCase("fr").includes(query) ? [index] : []);
  if (!matchingIndices.includes(activeSegment)) activeSegment = matchingIndices[0] ?? -1;
  pageIndex = Math.min(pageIndex, Math.max(0, Math.ceil(matchingIndices.length / PAGE_SIZE) - 1));
  matchingIndices.slice(pageIndex * PAGE_SIZE, (pageIndex + 1) * PAGE_SIZE).forEach(index => {
    const segment = working.segments[index];
    const row = document.createElement("div"); row.className = "segment"; row.dataset.index = index;
    const stamp = document.createElement("button"); stamp.className = "time";
    const start = document.createElement("span"), end = document.createElement("span"), action = document.createElement("span");
    start.textContent = timecode(segment.start); end.textContent = timecode(segment.end); action.textContent = "▶ Écouter";
    stamp.append(start, end, action); stamp.title = `Écouter de ${timecode(segment.start)} à ${timecode(segment.end)}`;
    stamp.setAttribute("aria-label", `Écouter le segment ${index+1}, début ${timecode(segment.start)}, fin ${timecode(segment.end)}`);
    stamp.addEventListener("click", () => { activateSegment(index); playSelected().catch(showError); });
    const textarea = document.createElement("textarea"); textarea.value = segment.text; textarea.dataset.index = index;
    textarea.rows = Math.min(8, Math.max(2, Math.ceil(segment.text.length / 85), segment.text.split("\n").length));
    textarea.spellcheck = false; // Avoid sending text to an enhanced browser spelling service.
    textarea.setAttribute("aria-label", `Segment ${index+1}, de ${timecode(segment.start)} à ${timecode(segment.end)}`);
    textarea.addEventListener("focus", () => activateSegment(index));
    textarea.addEventListener("input", () => { segment.text = textarea.value; changed(); });
    row.append(stamp, textarea); list.append(row);
  });
  if (!matchingIndices.length) { const empty = document.createElement("p"); empty.className = "muted"; empty.textContent = query ? "Aucun segment ne correspond à cette recherche." : "Aucun segment reconnu."; list.append(empty); }
  $("segmentCount").textContent = matchingIndices.length ? `${pageIndex*PAGE_SIZE+1}–${Math.min((pageIndex+1)*PAGE_SIZE,matchingIndices.length)} sur ${matchingIndices.length} segments${query ? " trouvés" : ""}` : "0 segment";
  $("previousPage").disabled = pageIndex === 0;
  $("nextPage").disabled = (pageIndex + 1) * PAGE_SIZE >= matchingIndices.length;
  updateSelection();
}
function updateSelection() {
  document.querySelectorAll("#segments .segment").forEach(row => row.classList.toggle("selected", Number(row.dataset.index) === activeSegment));
  const segment = working?.segments[activeSegment], position = matchingIndices.indexOf(activeSegment);
  $("selectionInfo").textContent = segment ? `Segment ${activeSegment+1} / ${working.segments.length} · ${timecode(segment.start)} — ${timecode(segment.end)}` : "Aucun segment sélectionné.";
  $("previousSegment").disabled = position <= 0;
  $("nextSegment").disabled = position < 0 || position >= matchingIndices.length-1;
  $("playSegment").disabled = !segment;
}
function activateSegment(index, focus=false) {
  if (!working?.segments[index]) return;
  activeSegment = index; preference(`segment.${currentId}`, index);
  const position = matchingIndices.indexOf(index);
  if (focus && position >= 0 && Math.floor(position/PAGE_SIZE) !== pageIndex) { pageIndex = Math.floor(position/PAGE_SIZE); renderSegments(); }
  updateSelection();
  if (focus) { const field = document.querySelector(`#segments textarea[data-index="${index}"]`); field?.focus({preventScroll:true}); field?.scrollIntoView({block:"nearest"}); }
}
function navigateSegment(delta) { const position = matchingIndices.indexOf(activeSegment), index = matchingIndices[position+delta]; if (index !== undefined) activateSegment(index, true); }
function clearClip() { clearTimeout(clipTimer); clipEnd = null; }
function enforceClipEnd() {
  if (clipEnd === null) return;
  const player = $("player");
  if (player.currentTime >= clipEnd - .015) { const end = clipEnd; clearClip(); player.pause(); player.currentTime = end; }
}
function scheduleClipEnd() {
  clearTimeout(clipTimer);
  const player = $("player");
  if (clipEnd === null || player.paused) return;
  clipTimer = setTimeout(() => { enforceClipEnd(); scheduleClipEnd(); }, Math.max(30, (clipEnd-player.currentTime)*1000/player.playbackRate));
}
async function playSelected() {
  const segment = working?.segments[activeSegment]; if (!segment) return;
  clearClip(); $("player").currentTime = segment.start; clipEnd = segment.end;
  await $("player").play(); scheduleClipEnd();
}
async function togglePlayback() { const player = $("player"); if (player.paused) { await player.play(); } else player.pause(); }
function skipAudio(delta) { clearClip(); const player = $("player"); player.currentTime = Math.max(0, Math.min(Number.isFinite(player.duration) ? player.duration : metadata.duration_seconds, player.currentTime+delta)); }
function pdfLink(name) { const link = $("lastPdf"); link.href = `/api/projects/${currentId}/files/${encodeURIComponent(name)}`; link.textContent = `Télécharger ${name}`; link.hidden = false; }
function openProject(id) {
  switchTask = switchTask.catch(() => {}).then(() => selectProject(id));
  return switchTask;
}
async function selectProject(id) {
  $("editing").inert = true;
  try {
  await flush(); clearError(); clearClip(); $("player").pause(); $("rawDialog").close(); $("rawText").textContent = "";
  currentId = id; working = null; metadata = await api(`/api/projects/${id}`);
  $("empty").hidden = true; $("editor").hidden = false; $("editing").hidden = true; $("lastPdf").hidden = true;
  $("sourceName").textContent = metadata.source_name;
  displayStatus();
  $("progress").textContent = metadata.stage + (metadata.error_code ? ` (${metadata.error_code})` : "");
  if (["DRAFT","VALIDATED"].includes(metadata.status)) {
    working = await api(`/api/projects/${id}/working`);
    $("title").value = working.title; $("participants").value = working.participants;
    $("player").src = `/api/projects/${id}/media`;
    $("saveState").textContent = "Enregistré"; $("editing").hidden = false;
    $("validate").textContent = metadata.test ? "CRÉER UN PDF TEST — NON VALIDÉ" : "VALIDER ET CRÉER LE PDF";
    $("search").value = ""; activeSegment = Math.max(0, Math.min(Number(preference(`segment.${id}`)) || 0, working.segments.length-1));
    pageIndex = Math.floor(activeSegment/PAGE_SIZE); renderSegments(); preference("project", id);
    if (metadata.last_pdf) pdfLink(metadata.last_pdf);
  }
  await refreshProjects();
  } finally { $("editing").inert = false; }
}
async function refreshProjects() {
  const projects = await api("/api/projects"), container = $("projects"); container.replaceChildren();
  if (!projects.length) { const empty = document.createElement("p"); empty.className = "muted"; empty.textContent = "Aucune transcription pour le moment."; container.append(empty); }
  for (const item of projects) {
    const button = document.createElement("button"); button.className = "project" + (item.id === currentId ? " active" : "");
    button.textContent = item.source_name; const subtitle = document.createElement("small");
    subtitle.textContent = `${item.test ? "TEST · " : ""}${statusLabel(item.status)} · ${new Date(item.created_at).toLocaleDateString("fr-FR")}`;
    button.append(subtitle); button.addEventListener("click", () => openProject(item.id).catch(showError)); container.append(button);
  }
  return projects;
}
async function refreshInbox() {
  const names = await api("/api/inbox"), select = $("inbox"); select.replaceChildren(new Option("Choisir…", ""));
  names.forEach(name => select.add(new Option(name, name))); select.value = selectedInbox;
}
function choose(file) { selectedFile = file; selectedInbox = ""; $("inbox").value = ""; $("reference").value = ""; $("selected").textContent = file ? file.name : "Aucun fichier sélectionné"; }
$("file").addEventListener("change", () => choose($("file").files[0]));
$("drop").addEventListener("dragover", event => { event.preventDefault(); $("drop").classList.add("drag"); });
$("drop").addEventListener("dragleave", () => $("drop").classList.remove("drag"));
$("drop").addEventListener("drop", event => { event.preventDefault(); $("drop").classList.remove("drag"); choose(event.dataTransfer.files[0]); });
$("inbox").addEventListener("change", () => { selectedInbox = $("inbox").value; selectedFile = null; $("reference").value = ""; $("selected").textContent = selectedInbox || "Aucun fichier sélectionné"; });
$("reference").addEventListener("input", () => { selectedFile = null; selectedInbox = ""; $("inbox").value = ""; $("selected").textContent = $("reference").value || "Aucun fichier sélectionné"; });
$("refreshInbox").addEventListener("click", () => refreshInbox().catch(showError));
$("refreshProjects").addEventListener("click", () => refreshProjects().catch(showError));
$("transcribe").addEventListener("click", async () => {
  if (processing) return;
  processing = true; $("transcribe").disabled = true; clearError();
  try {
    await flush();
    if (selectedFile) {
      $("availability").textContent = "Copie dans le dossier local…";
      const response = await fetch(`/api/upload?name=${encodeURIComponent(selectedFile.name)}`, {method:"POST", headers:{"X-LocalASR-Token":token}, body:selectedFile});
      const uploaded = await response.json(); if (!response.ok) throw new Error(uploaded.error);
      selectedInbox = uploaded.name; selectedFile = null;
    }
    const reference = $("reference").value.trim();
    if (!reference && !selectedInbox) throw new Error("Choisissez un fichier à transcrire.");
    const result = await api("/api/transcribe", {inbox_name:selectedInbox, reference, profile:$("profile").value, test:$("testMode").checked});
    $("availability").textContent = "Le traitement se poursuit localement."; await openProject(result.id);
  } catch (error) { showError(error); } finally { processing = false; $("transcribe").disabled = false; }
});
$("title").addEventListener("input", () => { working.title = $("title").value; changed(); });
$("participants").addEventListener("input", () => { working.participants = $("participants").value; changed(); });
$("search").addEventListener("input", () => { pageIndex = 0; renderSegments(); });
$("previousPage").addEventListener("click", () => { pageIndex--; renderSegments(); $("segments").scrollTop=0; });
$("nextPage").addEventListener("click", () => { pageIndex++; renderSegments(); $("segments").scrollTop=0; });
$("previousSegment").addEventListener("click", () => navigateSegment(-1));
$("nextSegment").addEventListener("click", () => navigateSegment(1));
$("playSegment").addEventListener("click", () => playSelected().catch(showError));
$("playPause").addEventListener("click", () => togglePlayback().catch(showError));
$("rewind").addEventListener("click", () => skipAudio(-3));
$("forward").addEventListener("click", () => skipAudio(3));
$("speed").value = ["0.75","1","1.25","1.5","2"].includes(preference("speed")) ? preference("speed") : "1";
$("player").playbackRate = Number($("speed").value);
$("speed").addEventListener("change", () => { $("player").playbackRate=Number($("speed").value); preference("speed",$("speed").value); });
$("player").addEventListener("timeupdate", enforceClipEnd);
for (const event of ["play","seeked","ratechange"]) $("player").addEventListener(event, scheduleClipEnd);
$("player").addEventListener("pause", () => clearTimeout(clipTimer));
$("showRaw").addEventListener("click", async () => {
  const id = currentId;
  try { await flush(); const raw=await api(`/api/projects/${id}/raw`); if(currentId !== id) return;
    $("rawText").textContent=raw.segments.map(s=>`[${timecode(s.start)} — ${timecode(s.end)}]\n${s.text}`).join("\n\n"); $("rawDialog").showModal();
  } catch(error) { showError(error); }
});
$("closeRaw").addEventListener("click", () => $("rawDialog").close());
$("rawDialog").addEventListener("close", () => { $("rawText").textContent=""; });
document.addEventListener("keydown", event => {
  if (!working || $("editing").inert || $("rawDialog").open) return;
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); flush().catch(showError); }
  else if (event.ctrlKey && event.key === "Enter") { event.preventDefault(); playSelected().catch(showError); }
  else if (event.altKey && ["ArrowUp","ArrowDown"].includes(event.key)) { event.preventDefault(); navigateSegment(event.key === "ArrowUp" ? -1 : 1); }
  else if (event.key === "F8") { event.preventDefault(); togglePlayback().catch(showError); }
});
$("save").addEventListener("click", () => flush().catch(showError));
$("reset").addEventListener("click", async () => {
  if (!confirm("Remplacer les corrections de travail par le texte brut ? Les versions PDF antérieures seront conservées.")) return;
  try { await flush(); await api(`/api/projects/${currentId}/reset`, {revision:working.revision}); await openProject(currentId); } catch(error) { showError(error); }
});
$("validate").addEventListener("click", async () => {
  $("validate").disabled = true; clearError();
  $("editing").inert = true;
  const id = currentId;
  try { await flush(); if (currentId !== id) return; const result = await api(`/api/projects/${id}/validate`, {revision:working.revision, test:metadata.test}); if (currentId === id) { pdfLink(result.name); metadata.status = result.test || dirty ? "DRAFT" : "VALIDATED"; displayStatus(); } await refreshProjects(); }
  catch(error) { showError(error); } finally { $("validate").disabled = false; $("editing").inert = false; }
});
document.querySelectorAll("[data-export]").forEach(button => button.addEventListener("click", async () => {
  const id = currentId;
  try { await flush(); if (currentId !== id) return; const result = await api(`/api/projects/${id}/export`, {format:button.dataset.export}); const link = document.createElement("a"); link.href = `/api/projects/${id}/files/${result.name}`; link.download = result.name; link.click(); } catch(error) { showError(error); }
}));
window.addEventListener("beforeunload", event => { if (dirty || saveTask) { event.preventDefault(); event.returnValue = ""; } });
let polling = false;
setInterval(async () => {
  if (polling || !currentId || working) return;
  polling = true;
  try { const item = await api(`/api/projects/${currentId}`); $("progress").textContent = item.stage; if (!["QUEUED","TRANSCRIBING"].includes(item.status)) await openProject(currentId); }
  catch(error) { showError(error); } finally { polling = false; }
}, 1800);
const appReady = (async () => { const config = await api("/api/config"); token = config.token; $("inboxPath").textContent = config.inbox;
  $("availability").textContent = config.ready ? "Prêt. Les résultats restent sur cet ordinateur." : "Le moteur attend l’autorisation des composants locaux. L’éditeur est disponible.";
  $("transcribe").disabled = !config.ready; const [projects] = await Promise.all([refreshProjects(), refreshInbox()]);
  const previous = preference("project"); if(projects.some(p=>p.id===previous)) await openProject(previous);
})();
appReady.catch(showError);
