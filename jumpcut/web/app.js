import WaveSurfer from './vendor/wavesurfer.esm.js'
import RegionsPlugin from './vendor/regions.esm.js'
import TimelinePlugin from './vendor/timeline.esm.js'

const $ = (s) => document.querySelector(s)
const TYPES = {
  silence: { label: '무음', rgb: '125,150,190' },
  filler: { label: '군말', rgb: '255,170,60' },
  repeat: { label: '반복', rgb: '255,95,115' },
  noise: { label: '잡음', rgb: '70,205,170' },
  user: { label: '직접', rgb: '165,125,255' },
}
const STAGES = {
  wait: '대기 중', audio: '오디오 읽는 중', model: '음성 인식 모델 내려받는 중 (처음 한 번, 약 1.6GB)',
  transcribe: '말 받아쓰는 중', detect: '자를 곳 찾는 중', export: '내보내는 중',
}

let P = null          // 현재 프로젝트
let cuts = []         // 편집 중인 컷(정본)
let spans = []        // 켜진 컷을 합친 구간
let sel = null        // 선택한 컷 id
let words = []        // 모든 단어 + core(실제로 소리 난 시각)
let wordEls = []
let ws = null, regions = null, rendering = false
let markIn = null     // 구간 자르기 시작점
let stopAt = null     // 듣기 버튼으로 재생할 때 멈출 시각
const undo = [], redo = []
const video = $('#video')

// ---------- 서버 ----------
async function api(path, opts = {}) {
  const json = opts.body && !(opts.body instanceof FormData)
  const res = await fetch(path, {
    ...opts,
    headers: json ? { 'content-type': 'application/json' } : {},
    body: json ? JSON.stringify(opts.body) : opts.body,
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText)
  return res.json()
}

async function waitJob(job, title) {
  overlay(title, 0, STAGES.wait)
  for (;;) {
    const j = await api(`/api/jobs/${job}`)
    if (j.error) throw new Error(j.error)
    if (j.done) return j.result
    overlay(title, j.progress, `${STAGES[j.stage] || j.stage} · ${Math.round(j.progress * 100)}%`)
    await new Promise((r) => setTimeout(r, 400))
  }
}

function overlay(title, frac, sub, actions = []) {
  $('#overlay').hidden = title == null
  if (title == null) return
  $('#ovTitle').textContent = title
  $('#ovBar').style.width = `${Math.round((frac || 0) * 100)}%`
  $('#ovSub').textContent = sub || ''
  $('#ovActions').replaceChildren(...actions.map(([label, fn, primary]) => {
    const b = document.createElement('button')
    b.textContent = label
    if (primary) b.className = 'primary'
    b.onclick = fn
    return b
  }))
}

const fail = (e) => overlay('문제가 생겼습니다', 0, e.message, [['닫기', () => overlay(null)]])

// ---------- 열기 ----------
async function openPath(path) {
  try { await afterOpen(await api('/api/open', { method: 'POST', body: { path } })) } catch (e) { fail(e) }
}

async function openUpload(file) {
  try {
    overlay('영상 불러오는 중', 0, file.name)
    const fd = new FormData()
    fd.append('file', file)
    await afterOpen(await api('/api/upload', { method: 'POST', body: fd }))
  } catch (e) { fail(e) }
}

async function afterOpen(res) {
  $('#fileName').textContent = res.name
  let data = res.project
  if (!data) {
    const lang = $('#lang').value
    const { job } = await api(`/api/project/${res.id}/analyze`, { method: 'POST', body: { language: lang === 'auto' ? null : lang } })
    data = await waitJob(job, '분석하는 중')
  }
  overlay(null)
  load(data)
}

async function pick() {
  const native = window.pywebview?.api?.pick_file
  if (!native) return $('#fileInput').click()
  const path = await native()
  if (path) openPath(path)
}
$('#btnOpen').onclick = pick
$('#btnOpen2').onclick = pick
$('#fileInput').onchange = (e) => e.target.files[0] && openUpload(e.target.files[0])

addEventListener('dragover', (e) => { e.preventDefault(); $('#drop').classList.add('over') })
addEventListener('dragleave', () => $('#drop').classList.remove('over'))
addEventListener('drop', (e) => {
  e.preventDefault()
  $('#drop').classList.remove('over')
  const f = e.dataTransfer.files[0]
  if (f && !window.pywebview) openUpload(f)   // 앱 창에서는 파이썬이 원본 경로를 받아 jumpcutOpen()을 부른다
})
window.jumpcutOpen = openPath

// ---------- 프로젝트 로드 ----------
function load(data) {
  P = data
  cuts = data.cuts.map((c) => ({ ...c }))
  undo.length = redo.length = 0
  sel = markIn = null
  words = P.segments.flatMap((s) => s.words).map((w) => ({ ...w, core: voicedTime(w) }))
  $('#empty').hidden = true
  $('#editor').hidden = false
  $('#btnExport').hidden = false
  $('#dur').textContent = fmt(P.duration)
  video.src = `/media/${P.id}`
  setupWave()
  setupTune()
  refresh()
}

/** Whisper의 단어 경계는 앞뒤 침묵까지 늘어나곤 해서, 파형이 큰 지점들의 가운데를 그 단어의 시각으로 본다. */
function voicedTime(w) {
  const loud = []
  for (let i = Math.floor(w.start * 100); i < Math.ceil(w.end * 100); i++) if (P.peaks[i] > 0.15) loud.push(i / 100)
  return loud.length ? loud[Math.floor(loud.length / 2)] : (w.start + w.end) / 2
}

function setupWave() {
  ws?.destroy()
  regions = RegionsPlugin.create()
  ws = WaveSurfer.create({
    container: '#wave',
    height: 92,
    waveColor: '#5d5d6a',
    progressColor: '#9d9dab',
    cursorColor: '#ffd23f',
    cursorWidth: 2,
    media: video,
    peaks: [P.peaks],
    duration: P.duration,
    normalize: true,
    autoScroll: true,
    autoCenter: true,
    plugins: [regions, TimelinePlugin.create({ height: 18, style: { color: '#8d8d98', fontSize: '11px' } })],
  })
  ws.on('ready', () => { addFilmstrip(); renderRegions() })   // 준비 전에 넣은 구간은 그려지지 않는다
  regions.enableDragSelection({ color: `rgba(${TYPES.user.rgb},.4)` })
  regions.on('region-created', (r) => {
    if (rendering) return
    r.remove()
    if (r.end - r.start >= 0.05) addUserCut(r.start, r.end, '직접 자름')
  })
  regions.on('region-updated', (r) => {
    const next = cuts.map((c) => (c.id === r.id ? { ...c, start: round(r.start), end: round(r.end) } : c))
    setTimeout(() => commit(next, r.id))
  })
  regions.on('region-clicked', (r, e) => { e.stopPropagation(); select(r.id, true) })
  $('#zoom').value = 0
}

/** 파형 위에 영상 썸네일 줄. 파형과 같은 래퍼 안에 넣어서 확대·스크롤·컷 색칠이 함께 움직인다. */
function addFilmstrip() {
  $('#wave').classList.toggle('has-film', !!P.has_video)
  if (!P.has_video) return
  const wrap = ws.getWrapper()
  const n = Math.max(6, Math.min(200, Math.ceil(wrap.clientWidth / 96)))
  const strip = document.createElement('div')
  strip.className = 'filmstrip'
  Object.assign(strip.style, { display: 'flex', height: '54px', marginBottom: '4px', background: '#000', borderRadius: '6px', overflow: 'hidden' })
  const url = `/api/project/${P.id}/thumbs?n=${n}`
  for (let i = 0; i < n; i++) {
    const cell = document.createElement('div')
    Object.assign(cell.style, {
      flex: '1', backgroundImage: `url(${url})`, backgroundSize: `${n * 100}% 100%`,
      backgroundPositionX: `${n > 1 ? (i / (n - 1)) * 100 : 0}%`, borderRight: '1px solid rgba(0,0,0,.35)',
    })
    strip.append(cell)
  }
  wrap.prepend(strip)
}

// ---------- 편집 ----------
const round = (x) => Math.round(x * 1000) / 1000

function commit(next, selectId = sel) {
  undo.push(cuts)
  redo.length = 0
  cuts = next
  sel = selectId
  refresh()
  save()
}

function step(from, to) {
  if (!from.length) return
  to.push(cuts)
  cuts = from.pop()
  refresh()
  save()
}

let saveTimer
function save() {
  clearTimeout(saveTimer)
  saveTimer = setTimeout(() => api(`/api/project/${P.id}/cuts`, { method: 'PUT', body: { cuts } }).catch(fail), 400)
}

function addUserCut(s, e, reason) {
  const id = `u-${Date.now()}`
  commit([...cuts, { id, source: 'user', type: 'user', reason, enabled: true, start: round(s), end: round(e) }], id)
}

const toggle = (id) => commit(cuts.map((c) => (c.id === id ? { ...c, enabled: !c.enabled } : c)), id)
const remove = (id) => commit(cuts.filter((c) => c.id !== id), null)

function select(id, seek) {
  sel = id
  const c = cuts.find((x) => x.id === id)
  if (c && seek) video.currentTime = Math.max(0, c.start - 0.8)
  refresh()
  document.querySelector(`#cutList li[data-id="${id}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
}

/** [s, e] 범위를 살린다: 걸친 컷은 잘라 내고, 안에 들어간 컷은 끈다. */
function keepRange(s, e) {
  const next = []
  for (const c of cuts) {
    if (!c.enabled || c.end <= s || c.start >= e) next.push(c)
    else if (c.start >= s && c.end <= e) next.push({ ...c, enabled: false })
    else {
      if (c.start < s) next.push({ ...c, end: s })
      if (c.end > e) next.push({ ...c, id: c.start < s ? `${c.id}-b${Date.now()}` : c.id, start: e })
    }
  }
  commit(next)
}

/** 컷 앞뒤 1.5초를 (잘린 상태 설정 그대로) 들려준다. */
function listen(c) {
  select(c.id)
  video.currentTime = Math.max(0, c.start - 1.5)
  stopAt = Math.min(P.duration, c.end + 1.5)
  video.play()
}

function jump(dir) {
  const sorted = [...cuts].sort((a, b) => a.start - b.start)
  const i = sorted.findIndex((x) => x.id === sel)
  let c
  if (i >= 0) c = sorted[i + dir]
  else {
    const t = video.currentTime
    c = dir > 0 ? sorted.find((x) => x.start > t) : sorted.reverse().find((x) => x.start < t)
  }
  if (c) select(c.id, true)
}

function mark() {
  const t = round(video.currentTime)
  if (markIn == null) markIn = t
  else {
    const [a, b] = [Math.min(markIn, t), Math.max(markIn, t)]
    markIn = null
    if (b - a >= 0.05) addUserCut(a, b, '직접 자름')
  }
  renderMark()
}

// ---------- 그리기 ----------
const typeOf = (c) => TYPES[c.type] || TYPES.user
const cutAt = (t) => cuts.filter((c) => c.enabled && t >= c.start && t < c.end).sort((a, b) => (a.end - a.start) - (b.end - b.start))[0]

function mergeSpans() {
  const on = cuts.filter((c) => c.enabled).map((c) => [Math.max(0, c.start), Math.min(P.duration, c.end)]).sort((a, b) => a[0] - b[0])
  const out = []
  for (const [a, b] of on) {
    if (b - a < 0.02) continue
    const last = out[out.length - 1]
    if (last && a <= last[1] + 0.02) last[1] = Math.max(last[1], b)
    else out.push([a, b])
  }
  return out
}

function refresh() {
  spans = mergeSpans()
  const removed = spans.reduce((s, [a, b]) => s + b - a, 0)
  const on = cuts.filter((c) => c.enabled).length
  $('#summaryTop').innerHTML = `${fmtSec(P.duration)} → <b>${fmtSec(P.duration - removed)}</b>`
  $('#savedSec').textContent = `−${removed.toFixed(1)}초`
  $('#savedSub').textContent = `${on}곳 자름 · 원래 길이의 ${Math.round((removed / P.duration) * 100)}% 줄어듦`
  $('#tToggle').disabled = $('#tDelete').disabled = !sel
  renderRegions()
  renderTypes()
  renderList()
  renderScript()
  renderMark()
}

function renderRegions() {
  if (!regions) return
  rendering = true
  regions.clearRegions()
  for (const c of cuts) {
    const r = regions.addRegion({
      id: c.id, start: c.start, end: c.end, drag: false, resize: true,
      color: `rgba(${typeOf(c).rgb},${c.enabled ? 0.42 : 0.1})`,
    })
    if (c.id === sel) r.element.style.boxShadow = 'inset 0 0 0 2px #ffd23f'
    r.element.title = `${c.reason}${c.enabled ? '' : ' (살림)'}`
  }
  rendering = false
}

function renderTypes() {
  const present = Object.entries(TYPES).filter(([t]) => cuts.some((c) => c.type === t))
  $('#typeRows').replaceChildren(...present.map(([t, v]) => {
    const all = cuts.filter((c) => c.type === t)
    const on = all.filter((c) => c.enabled)
    const sec = on.reduce((s, c) => s + c.end - c.start, 0)
    const row = document.createElement('div')
    row.className = 'type-row'
    row.innerHTML = `<span class="dot" style="background:rgb(${v.rgb})"></span><span>${v.label}</span>
      <span class="n mono">${on.length}/${all.length} · ${sec.toFixed(1)}초</span>
      <label class="switch" title="${v.label} 모두 ${on.length ? '살리기' : '자르기'}"><input type="checkbox" ${on.length ? 'checked' : ''}><i></i></label>`
    row.querySelector('input').onchange = (e) => commit(cuts.map((c) => (c.type === t ? { ...c, enabled: e.target.checked } : c)))
    return row
  }))
  $('#legend').innerHTML = present.map(([, v]) => `<span><i style="background:rgb(${v.rgb})"></i>${v.label}</span>`).join('')
}

const esc = (s) => s.replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]))

/** “…드릴게요. [⏸1.7초] 어, 이…” 처럼 컷 앞뒤 말을 붙여 보여 준다. */
function context(c) {
  const before = words.filter((w) => w.core < c.start).slice(-3)
  const inside = words.filter((w) => w.core >= c.start && w.core < c.end)
  const after = words.filter((w) => w.core >= c.end).slice(0, 3)
  const mid = inside.length ? inside.map((w) => w.word).join(' ') : c.type === 'silence' ? `⏸ ${(c.end - c.start).toFixed(1)}초` : c.reason
  const join = (ws) => esc(ws.map((w) => w.word).join(' '))
  return `${before.length ? '…' + join(before) : ''} <mark>${esc(mid)}</mark> ${after.length ? join(after) + '…' : ''}`
}

function renderList() {
  const sorted = [...cuts].sort((a, b) => a.start - b.start)
  $('#cutList').replaceChildren(...sorted.map((c) => {
    const v = typeOf(c)
    const li = document.createElement('li')
    li.dataset.id = c.id
    li.className = `${c.enabled ? '' : 'off'} ${c.id === sel ? 'sel' : ''}`
    li.style.setProperty('--c', `rgb(${v.rgb})`)
    li.innerHTML = `<div class="row">
        <span class="tag" style="background:rgba(${v.rgb},.18);color:rgb(${v.rgb})">${v.label}</span>
        <span class="t mono">${fmt(c.start)} · ${(c.end - c.start).toFixed(1)}초</span>
        <span class="btns"><button data-a="listen" title="앞뒤 1.5초를 들어 봅니다">▶ 듣기</button>
        <button data-a="toggle">${c.enabled ? '살리기' : '자르기'}</button>
        ${c.source === 'user' ? '<button data-a="del" title="지우기">✕</button>' : ''}</span>
      </div><div class="ctx">${context(c)}</div>`
    li.onclick = (e) => {
      const a = e.target.dataset?.a
      if (a === 'listen') listen(c)
      else if (a === 'toggle') toggle(c.id)
      else if (a === 'del') remove(c.id)
      else select(c.id, true)
    }
    return li
  }))
}

function renderScript() {
  const box = $('#script')
  const scroll = box.parentElement.scrollTop
  // 말이 없는 컷(무음·잡음)은 자막 사이에 알약으로 끼워 넣는다
  const pills = cuts.filter((c) => !words.some((w) => w.core >= c.start && w.core < c.end)).sort((a, b) => a.start - b.start)
  let pi = 0
  const pill = (c) => {
    const v = typeOf(c)
    const el = document.createElement('span')
    el.className = `pill ${c.enabled ? '' : 'off'}`
    el.style.cssText = `color:rgb(${v.rgb});border-color:rgba(${v.rgb},.5);background:rgba(${v.rgb},.12)`
    el.textContent = c.type === 'silence' ? `⏸ ${(c.end - c.start).toFixed(1)}초` : c.type === 'noise' ? c.reason.replace(' 소리', '') : v.label
    el.title = c.enabled ? '클릭하면 살립니다' : '클릭하면 자릅니다'
    el.onclick = () => toggle(c.id)
    return el
  }
  let wi = 0   // words는 segments의 단어를 순서대로 펼친 것이라 같은 순서로 짝지어진다
  const segs = P.segments.map((s) => {
    const p = document.createElement('span')
    p.className = 'seg'
    for (const w of s.words) {
      const ww = words[wi++]
      while (pi < pills.length && pills[pi].start <= ww.core) p.append(pill(pills[pi++]), ' ')
      const el = document.createElement('span')
      el.className = 'w'
      el.textContent = w.word
      el.dataset.s = ww.start
      el.dataset.e = ww.end
      const c = cutAt(ww.core)
      if (c) {
        el.classList.add('cut')
        el.style.setProperty('--c', `rgb(${typeOf(c).rgb})`)
        if (c.id === sel) el.classList.add('sel')
      }
      el.onclick = () => {
        if (getSelection().toString()) return
        if (c) select(c.id, true)
        else video.currentTime = ww.start
      }
      p.append(el, ' ')
    }
    return p
  })
  const tail = document.createElement('span')
  while (pi < pills.length) tail.append(pill(pills[pi++]), ' ')
  box.replaceChildren(...segs, tail)
  wordEls = [...box.querySelectorAll('.w')]
  box.parentElement.scrollTop = scroll
}

function renderMark() {
  $('#markHint').textContent = markIn == null ? '' : `시작점 ${fmt(markIn)} · 끝점에서 다시 누르세요 (O)`
  $('#tMark').classList.toggle('primary', markIn != null)
}

const fmt = (t) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, '0')}`
const fmtSec = (t) => (t >= 60 ? `${Math.floor(t / 60)}분 ${Math.round(t % 60)}초` : `${t.toFixed(1)}초`)

// ---------- 자막에서 범위 고르기 ----------
let picked = null
$('#script').addEventListener('mouseup', (e) => {
  const s = getSelection()
  const chosen = wordEls.filter((el) => s.containsNode(el, true))
  if (!s.toString().trim() || !chosen.length) return hideSel()
  picked = [+chosen[0].dataset.s, +chosen[chosen.length - 1].dataset.e, s.toString().trim().slice(0, 20)]
  const bar = $('#selBar')
  bar.hidden = false
  bar.style.left = `${Math.min(e.clientX - 40, innerWidth - 220)}px`
  bar.style.top = `${e.clientY + 14}px`
})
function hideSel() { $('#selBar').hidden = true; picked = null }
document.addEventListener('mousedown', (e) => {
  if (!$('#selBar').contains(e.target)) hideSel()
  if (!$('#helpPop').contains(e.target) && e.target !== $('#help')) $('#helpPop').hidden = true
})
$('#selCut').onclick = () => { addUserCut(picked[0], picked[1], `직접 자름 “${picked[2]}”`); getSelection().removeAllRanges(); hideSel() }
$('#selKeep').onclick = () => { keepRange(picked[0], picked[1]); getSelection().removeAllRanges(); hideSel() }

// ---------- 재생 ----------
const playPause = () => (video.paused ? video.play() : video.pause())
$('#btnPlay').onclick = playPause
$('#btnPrev').onclick = () => jump(-1)
$('#btnNext').onclick = () => jump(1)
video.onplay = () => ($('#btnPlay').textContent = '❚❚')
video.onpause = () => { $('#btnPlay').textContent = '▶'; stopAt = null }

let lastWord = null
function tick() {
  if (P) {
    const t = video.currentTime
    if (!video.paused) {
      if ($('#preview').checked) {
        const hit = spans.find(([a, b]) => t >= a && t < b - 0.01)
        if (hit) video.currentTime = hit[1]
      }
      if (stopAt != null && t >= stopAt) video.pause()
    }
    $('#time').textContent = fmt(t)
    const now = wordEls.find((el) => t >= +el.dataset.s && t < +el.dataset.e)
    if (now !== lastWord) {
      lastWord?.classList.remove('now')
      now?.classList.add('now')
      lastWord = now
    }
  }
  requestAnimationFrame(tick)
}
requestAnimationFrame(tick)

// ---------- 타임라인 도구 ----------
const setZoom = (v) => { $('#zoom').value = v; try { ws?.zoom(+v) } catch {} }
$('#zoom').oninput = (e) => setZoom(e.target.value)
$('#zIn').onclick = () => setZoom(Math.min(400, +$('#zoom').value + 40))
$('#zOut').onclick = () => setZoom(Math.max(0, +$('#zoom').value - 40))
$('#tUndo').onclick = () => step(undo, redo)
$('#tRedo').onclick = () => step(redo, undo)
$('#tMark').onclick = mark
$('#tToggle').onclick = () => sel && toggle(sel)
$('#tDelete').onclick = () => sel && remove(sel)
$('#help').onclick = () => ($('#helpPop').hidden = !$('#helpPop').hidden)

// ---------- 기준 조정 ----------
const TUNE = [
  ['p_min', 'o_min', 'min_silence', (v) => `${(+v).toFixed(2)}초`],
  ['p_sens', 'o_sens', 'sensitivity', (v) => (+v).toFixed(2)],
  ['p_pad', 'o_pad', 'keep_pad', (v) => `${(+v).toFixed(2)}초`],
  ['p_noise', 'o_noise', 'noise_score', (v) => (+v).toFixed(2)],
]
function setupTune() {
  for (const [inp, out, key, show] of TUNE) {
    const el = $(`#${inp}`)
    el.value = P.params[key] ?? el.value
    $(`#${out}`).textContent = show(el.value)
    el.oninput = () => ($(`#${out}`).textContent = show(el.value))
    el.onchange = () => retune({ [key]: +el.value })
  }
}
async function retune(params) {
  try {
    clearTimeout(saveTimer)   // 저장 대기 중인 편집은 아래 요청에 실어 보낸다
    const data = await api(`/api/project/${P.id}/redetect`, { method: 'POST', body: { params, cuts } })
    P.params = data.params
    commit(data.cuts.map((c) => ({ ...c })), null)
  } catch (e) { fail(e) }
}

// ---------- 내보내기 ----------
$('#btnExport').onclick = async () => {
  try {
    await api(`/api/project/${P.id}/cuts`, { method: 'PUT', body: { cuts } })
    const { job } = await api(`/api/project/${P.id}/export`, { method: 'POST' })
    const { path } = await waitJob(job, '내보내는 중')
    overlay('다 됐습니다', 1, path, [
      ['Finder에서 보기', () => api('/api/reveal', { method: 'POST', body: { path } }), true],
      ['닫기', () => overlay(null)],
    ])
  } catch (e) { fail(e) }
}

// ---------- 단축키 ----------
addEventListener('keydown', (e) => {
  if (!P || e.target.matches?.('input, select, textarea')) return
  const k = e.key.toLowerCase()
  if ((e.metaKey || e.ctrlKey) && k === 'z') { e.preventDefault(); e.shiftKey ? step(redo, undo) : step(undo, redo); return }
  if (e.metaKey || e.ctrlKey) return
  if (e.code === 'Space') { e.preventDefault(); playPause() }
  else if (k === 'x') { if (sel) toggle(sel) }
  else if (k === 'backspace' || k === 'delete') { if (sel) { e.preventDefault(); remove(sel) } }
  else if (k === 'p') $('#preview').checked = !$('#preview').checked
  else if (k === '[') jump(-1)
  else if (k === ']') jump(1)
  else if (k === 'i') { markIn = null; mark() }
  else if (k === 'o') { if (markIn != null) mark() }
  else if (k === 'escape') { markIn = null; renderMark(); $('#helpPop').hidden = true }
  else if (k === 'arrowleft') video.currentTime = Math.max(0, video.currentTime - (e.shiftKey ? 5 : 1))
  else if (k === 'arrowright') video.currentTime = Math.min(P.duration, video.currentTime + (e.shiftKey ? 5 : 1))
})
