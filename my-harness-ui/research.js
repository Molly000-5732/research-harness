(() => {
  const labels = {
    chat: '会话', overview: '研究总览', library: '文献库',
    questions: '问题调研', painpoints: '痛点定位', plan: '方案规划', experiment: '实验验证',
  };
  const firstMessages = {
    questions: '请搜索相关论文、整理文献，并提出可研究的问题。',
    painpoints: '请根据已确认问题和逐篇论文材料提出有证据的痛点。',
    plan: '请根据项目背景和已选痛点拟定研究方案。',
    experiment: '请在当前项目执行已确认方案中的实验，并根据实际结果进行分析。',
  };
  const confirmationLabels = {
    questions: '确认研究问题', painpoints: '确认痛点', plan: '确认方案', experiment: '保存实验结论',
  };
  let view = 'chat';
  let project = null;
  let research = null;
  let snapshot = null;
  let selection = 0;
  let dialogAction;

  function route(suffix = '') {
    return `/api/projects/${project}/research${suffix}`;
  }

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function button(text, action, className = 'secondary') {
    const node = element('button', text, className);
    node.type = 'button';
    node.addEventListener('click', async () => {
      node.disabled = true;
      try { await action(); }
      catch (error) { showError(error.message); }
      finally { node.disabled = false; }
    });
    return node;
  }

  function openEditor(title, label, content, action) {
    $('#research-dialog-title').textContent = title;
    $('#research-content-label').textContent = label;
    $('#research-content').value = content;
    $('#research-dialog-error').hidden = true;
    dialogAction = action;
    $('#research-dialog').showModal();
  }

  $('#research-dismiss').addEventListener('click', () => $('#research-dialog').close());
  $('#research-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const submit = event.submitter;
    submit.disabled = true;
    try {
      await dialogAction($('#research-content').value);
      $('#research-dialog').close();
    } catch (error) {
      $('#research-dialog-error').textContent = error.message;
      $('#research-dialog-error').hidden = false;
    } finally { submit.disabled = false; }
  });

  function showNavigation() {
    const nav = $('#research-nav');
    nav.hidden = !project;
    nav.replaceChildren(...Object.entries(labels).map(([key, title]) => {
      const item = button(title, () => selectView(key), 'research-tab');
      item.setAttribute('aria-current', key === view ? 'page' : 'false');
      return item;
    }));
    $('#session-list').hidden = view !== 'chat';
  }

  function renderPanel() {
    const panel = $('#research-panel');
    panel.hidden = view === 'chat';
    panel.classList.toggle('research-full', view === 'overview' || view === 'library');
    panel.replaceChildren();
    if (view === 'chat' || !research) return;
    if (view === 'overview') {
      const projectRoute = route();
      panel.append(element('h2', '项目背景'), element('p', research.background || '先填写研究方向、目标和已有资料。'),
        button('编辑背景', () => openEditor('项目背景', '研究背景', research.background, async (background) => {
          research = await api(projectRoute, { background });
          renderPanel();
        })));
      const grid = element('div', '', 'research-grid');
      for (const [stage, item] of Object.entries(research.stages)) {
        const status = item.stale ? '输入已更新' : item.valid ? '已确认' : item.ready ? '待开展'
          : research.background ? '等待前序阶段' : '等待项目背景';
        grid.append(button(`${item.title} · ${status}`, () => selectView(stage)));
      }
      panel.append(grid);
      return;
    }
    if (view === 'library') {
      panel.append(element('h2', '已确认的调研文献'));
      if (!research.papers.length) panel.append(element('p', '在问题调研中搜索论文并确认研究问题后，文献会出现在这里。'));
      for (const paper of research.papers) {
        const entry = element('article', '', 'paper-entry');
        entry.append(element('h3', paper.title), element('p', `摘要　${paper.abstract || '未取得'}`),
          element('p', `AI 分析　${paper.analysis || '暂无'}`));
        const link = element('a', '打开来源');
        link.href = paper.url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        entry.append(link);
        panel.append(entry);
      }
      return;
    }
    const stage = research.stages[view];
    const actions = element('div', '', 'research-actions');
    actions.append(element('h2', stage.title));
    const start = button(view === 'experiment' ? '运行实验' : '开始生成', async () => {
      $('#message').value = firstMessages[view];
      $('#chat').requestSubmit();
    }, 'primary');
    start.disabled = !stage.ready || state.busy || !state.sessionId;
    actions.append(start);
    panel.append(actions);
    if (!stage.ready || stage.stale) {
      panel.append(element('p', !stage.ready ? '请先保存背景并确认前一阶段结果。' :
        '上游输入已更新。继续对话时会提供新的确认内容，旧结果仍可查看。', 'research-warning'));
    }
    const last = snapshot?.runs?.at(-1);
    if (last?.status === 'completed' && last.reply && stage.ready && stage.draft_current && !state.busy) {
      const confirmPath = route(`/${view}/confirm`);
      const title = confirmationLabels[view];
      const draft = view === 'questions' ? last.reply.replace(/```json\s*[\s\S]*?```/gi, '').trim() : last.reply;
      actions.append(button(title, () => openEditor(title, '编辑要保存的内容', draft, async (content) => {
        research = await api(confirmPath, { run_id: last.id, content });
        renderPanel();
      })));
    }
    if (stage.revisions.length) {
      const details = element('details', '', 'research-revisions');
      details.append(element('summary', stage.valid ? '查看已确认内容与历史版本' : '查看历史确认版本'));
      for (const revision of stage.revisions) {
        const version = element('details');
        version.append(element('summary', new Date(revision.created_at).toLocaleString()), element('pre', revision.content));
        details.append(version);
      }
      panel.append(details);
    }
  }

  async function selectView(key) {
    if (!project) return;
    const current = ++selection;
    const projectId = project;
    clearTimeout(state.timer);
    state.version += 1;
    state.sessionId = null;
    state.snapshot = '';
    snapshot = null;
    view = key;
    $('#messages').replaceChildren();
    $('#empty-state').hidden = key !== 'chat';
    $('#approval-panel').hidden = true;
    $('#status').textContent = labels[key];
    $('#conversation').hidden = key === 'overview' || key === 'library';
    $('#chat').hidden = $('#conversation').hidden;
    save(`view.${projectId}`, key);
    showError();
    showNavigation();
    setComposer();
    if (key === 'chat') {
      $('#research-panel').hidden = true;
      const session = state.sessions.find((item) => item.id === saved('session')) || state.sessions[0];
      if (session) await selectSession(session.id);
      return;
    }
    const value = await api(route());
    if (current !== selection) return;
    research = value;
    renderPanel();
    if (key === 'overview' || key === 'library') return;
    const data = await api(route(`/${key}/session`), {});
    if (current === selection) await selectSession(data.session_id);
  }

  async function showApproval(run, version) {
    const panel = $('#approval-panel');
    const result = run && activeStatuses.has(run.status) ? await api(`/api/runs/${run.id}/approval`) : {};
    if (state.version !== version) return;
    const approval = result.approval;
    const fingerprint = JSON.stringify(approval || null);
    if (fingerprint === panel.dataset.approval && !panel.hidden) return;
    panel.dataset.approval = fingerprint;
    panel.hidden = !approval;
    panel.replaceChildren();
    if (!approval) return;
    panel.append(element('strong', `工具审批　${approval.tool}`), element('p', approval.reason),
      element('pre', approval.arguments || '正在等待可审阅的工具参数。'));
    const reply = (outcome) => async () => {
      await api(`/api/runs/${run.id}/approval`, { id: approval.id, outcome });
      await refreshSession(version);
    };
    const allow = button('批准一次', reply('allowed-once'), 'primary');
    allow.disabled = !approval.arguments;
    panel.append(allow, button('拒绝', reply('rejected')));
  }

  window.researchUI = {
    reset() {
      selection += 1;
      project = state.projectId;
      view = 'chat';
      research = null;
      snapshot = null;
      $('#chat').hidden = false;
      $('#conversation').hidden = false;
      $('#approval-panel').hidden = true;
      $('#research-panel').hidden = true;
      showNavigation();
    },
    async restore(id) {
      const preferred = saved(`view.${id}`);
      if (preferred && preferred !== 'chat' && Object.hasOwn(labels, preferred) && view === 'chat') {
        await selectView(preferred);
      }
    },
    chatPath() { return Object.hasOwn(firstMessages, view) ? route(`/${view}/chat`) : null; },
    composer() {
      if (research?.stages[view] && !research.stages[view].ready) {
        $('#send').disabled = $('#message').disabled = true;
      }
    },
    async refresh(data, version) {
      if (!Object.hasOwn(firstMessages, view)) {
        $('#approval-panel').hidden = true;
        return;
      }
      const next = await api(route());
      if (state.version !== version) return;
      research = next;
      snapshot = data;
      this.composer(state.busy);
      renderPanel();
      await showApproval(data.runs.at(-1), version);
    },
  };
  window.researchUI.reset();
})();
