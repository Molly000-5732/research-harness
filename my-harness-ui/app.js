const $ = (selector) => document.querySelector(selector);
const state = { projects: [], sessions: [], projectId: null, sessionId: null, version: 0, timer: null, busy: false, snapshot: '' };
const activeStatuses = new Set(['queued', 'running']);
const statusLabels = { queued: '等待执行', running: '执行中', completed: '已完成', error: '执行失败', interrupted: '结果待确认' };

function saved(key) {
  try { return JSON.parse(localStorage.getItem(`research.${key}`)); }
  catch { return null; }
}

function save(key, value) {
  try { localStorage.setItem(`research.${key}`, JSON.stringify(value)); }
  catch { /* The server still persists all session data when browser storage is disabled. */ }
}

async function api(path, body) {
  const options = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `请求失败 (${response.status})`);
  return data;
}

function showError(message = '') {
  $('#error').textContent = message;
  $('#error').hidden = !message;
}

function navItem(text, active, action) {
  const button = document.createElement('button');
  button.className = `nav-item${active ? ' active' : ''}`;
  button.textContent = text;
  button.setAttribute('aria-current', active ? 'true' : 'false');
  button.addEventListener('click', () => action().catch((error) => showError(error.message)));
  return button;
}

function renderNavigation() {
  $('#projects').replaceChildren(...state.projects.map((project) => navItem(project.name, project.id === state.projectId, () => selectProject(project.id))));
  $('#sessions').replaceChildren(...state.sessions.map((session) => navItem(session.title, session.id === state.sessionId, () => selectSession(session.id))));
  $('#new-session').disabled = !state.projectId;
  if (!state.projects.length) $('#projects').textContent = '还没有项目';
  if (state.projectId && !state.sessions.length) $('#sessions').textContent = '新建一个会话开始研究';
}

function setComposer(busy = false) {
  state.busy = busy;
  $('#message').disabled = !state.sessionId || busy;
  $('#send').disabled = !state.sessionId || busy;
  $('#send').textContent = busy ? '正在执行…' : '发送消息 ↑';
  $('#session-hint').textContent = state.sessionId ? '对话历史自动保存在本机' : '请选择项目并新建会话';
}

async function selectProject(id, preferredSession = null) {
  clearTimeout(state.timer);
  state.version += 1;
  const version = state.version;
  state.projectId = id;
  state.sessionId = null;
  state.sessions = [];
  state.snapshot = '';
  save('project', id);
  const project = state.projects.find((item) => item.id === id);
  $('#project-title').textContent = project.name;
  $('#project-directory').textContent = project.directory;
  $('#messages').replaceChildren();
  $('#empty-state').hidden = false;
  $('#empty-add').hidden = true;
  $('#status').textContent = '就绪';
  showError();
  setComposer();
  renderNavigation();
  const data = await api(`/api/projects/${id}/sessions`);
  if (state.version !== version) return;
  state.sessions = data.sessions;
  renderNavigation();
  const session = state.sessions.find((item) => item.id === preferredSession) || state.sessions[0];
  if (session) await selectSession(session.id);
}

async function selectSession(id) {
  clearTimeout(state.timer);
  const previousId = state.sessionId;
  if (previousId) save(`draft.${previousId}`, $('#message').value);
  state.version += 1;
  state.sessionId = id;
  state.snapshot = '';
  save('session', id);
  $('#message').value = saved(`draft.${id}`) || '';
  $('#messages').replaceChildren();
  showError();
  renderNavigation();
  setComposer(true);
  await refreshSession(state.version);
}

function addNote(text, failed = false) {
  const note = document.createElement('div');
  note.className = `run-note${failed ? ' failed' : ''}`;
  note.textContent = text;
  $('#messages').append(note);
}

function renderConversation(data) {
  const snapshot = JSON.stringify(data);
  if (snapshot === state.snapshot) return;
  const conversation = $('#conversation');
  const followBottom = !state.snapshot || conversation.scrollHeight - conversation.scrollTop - conversation.clientHeight < 100;
  state.snapshot = snapshot;
  $('#messages').replaceChildren();
  $('#empty-state').hidden = data.messages.length > 0;
  for (const run of data.runs) {
    for (const message of data.messages.filter((item) => item.run_id === run.id)) {
      const article = document.createElement('article');
      article.className = `message ${message.role}`;
      const label = document.createElement('div');
      label.className = 'message-label';
      label.textContent = message.role === 'user' ? '你' : 'Research Harness';
      const body = document.createElement('div');
      body.className = 'message-body';
      body.textContent = message.content;
      article.append(label, body);
      $('#messages').append(article);
    }
    for (const notice of run.notices) addNote(notice);
    if (run.error) addNote(run.error, true);
    if (activeStatuses.has(run.status)) addNote('Harness 正在执行任务，完成后将在这里显示结果。');
    if (run.status === 'completed' && !run.reply) addNote('操作已完成，未返回文本。');
  }
  if (followBottom) conversation.scrollTop = conversation.scrollHeight;
}

async function refreshSession(version) {
  clearTimeout(state.timer);
  if (version !== state.version) return;
  try {
    const data = await api(`/api/sessions/${state.sessionId}`);
    if (version !== state.version) return;
    renderConversation(data);
    const last = data.runs.at(-1);
    const busy = Boolean(last && activeStatuses.has(last.status));
    setComposer(busy);
    $('#status').textContent = last ? statusLabels[last.status] : '新会话';
    const session = state.sessions.find((item) => item.id === state.sessionId);
    if (session) session.title = data.session.title;
    renderNavigation();
    if (busy) state.timer = setTimeout(() => refreshSession(version), 1000);
  } catch (error) {
    if (version !== state.version) return;
    showError(error.message);
    $('#status').textContent = '连接失败';
    setComposer();
    state.timer = setTimeout(() => refreshSession(version), 3000);
  }
}

$('#chat').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (state.busy || !state.sessionId || !$('#message').value.trim()) return;
  const version = state.version;
  const message = $('#message').value.trim();
  const previous = saved('pending');
  const request = previous && previous.session_id === state.sessionId && previous.message === message
    ? previous : { session_id: state.sessionId, request_id: crypto.randomUUID(), message };
  save('pending', request);
  setComposer(true);
  showError();
  try {
    await api('/api/chat', request);
    save('pending', null);
    save(`draft.${request.session_id}`, '');
    if (version !== state.version) return;
    $('#message').value = '';
    await refreshSession(version);
  } catch (error) {
    if (version !== state.version) return;
    setComposer();
    showError(error.message);
    await refreshSession(version);
  }
});

$('#message').addEventListener('input', () => save(`draft.${state.sessionId}`, $('#message').value));
$('#new-session').addEventListener('click', async () => {
  const projectId = state.projectId;
  $('#new-session').disabled = true;
  try {
    const data = await api(`/api/projects/${projectId}/sessions`, {});
    if (projectId !== state.projectId) return;
    state.sessions.unshift(data.session);
    await selectSession(data.session.id);
  } catch (error) { showError(error.message); }
  finally { $('#new-session').disabled = !state.projectId; }
});

function openProjectDialog() {
  $('#project-error').hidden = true;
  $('#project-dialog').showModal();
}
$('#add-project').addEventListener('click', openProjectDialog);
$('#empty-add').addEventListener('click', openProjectDialog);
$('#cancel-project').addEventListener('click', () => $('#project-dialog').close());
$('#project-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  $('#save-project').disabled = true;
  try {
    const data = await api('/api/projects', { name: $('#project-name').value, directory: $('#project-path').value });
    state.projects = (await api('/api/projects')).projects;
    $('#project-dialog').close();
    $('#project-form').reset();
    await selectProject(data.project.id);
  } catch (error) {
    $('#project-error').textContent = error.message;
    $('#project-error').hidden = false;
  } finally { $('#save-project').disabled = false; }
});

async function initialize() {
  state.projects = (await api('/api/projects')).projects;
  renderNavigation();
  const project = state.projects.find((item) => item.id === saved('project')) || state.projects[0];
  if (project) await selectProject(project.id, saved('session'));
}
initialize().catch((error) => showError(error.message));
