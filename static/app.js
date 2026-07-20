const state = {
  token: localStorage.getItem('sber_mvp_token') || '',
  user: null,
  page: 'dashboard',
  dashboard: null,
  documents: [],
  tasks: [],
  onboarding: null,
  chat: [],
  admin: null,
};

const roleLabels = {
  newcomer: 'Новый сотрудник', employee: 'Сотрудник', manager: 'Руководитель',
  expert: 'Эксперт', developer: 'ИТ-разработчик', admin: 'Администратор'
};
const demoAccounts = [
  {login:'anna', pass:'demo123', initials:'АС', label:'Новичок'},
  {login:'dmitry', pass:'demo123', initials:'ДВ', label:'Сотрудник'},
  {login:'elena', pass:'demo123', initials:'ЕО', label:'Руководитель'},
  {login:'sergey', pass:'demo123', initials:'СК', label:'Эксперт'},
  {login:'alexey', pass:'demo123', initials:'АМ', label:'Разработчик'},
  {login:'admin', pass:'admin123', initials:'МА', label:'Администратор'},
];

const navConfig = [
  {id:'dashboard', label:'Главная', icon:'⌂', roles:['all']},
  {id:'assistant', label:'ИИ-ассистент', icon:'✦', roles:['all']},
  {id:'knowledge', label:'База знаний', icon:'▤', roles:['all']},
  {id:'onboarding', label:'Моя адаптация', icon:'◉', roles:['newcomer']},
  {id:'meetings', label:'Встречи', icon:'◎', roles:['all']},
  {id:'documents', label:'Анализ файлов', icon:'▧', roles:['all']},
  {id:'tasks', label:'Мои задачи', icon:'✓', roles:['all']},
  {id:'analytics', label:'Аналитика', icon:'▥', roles:['manager','admin']},
  {id:'admin', label:'Управление', icon:'⚙', roles:['admin']},
];

const pageNames = {
  dashboard:'Главная', assistant:'ИИ-ассистент', knowledge:'База знаний', onboarding:'Моя адаптация',
  meetings:'Встречи', documents:'Анализ файлов', tasks:'Мои задачи', analytics:'Аналитика', admin:'Управление'
};

function $(selector, root=document){ return root.querySelector(selector); }
function $$(selector, root=document){ return [...root.querySelectorAll(selector)]; }
function escapeHtml(value=''){ return String(value).replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch])); }
function formatDate(value){ if(!value) return 'Без срока'; const d = new Date(value); return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString('ru-RU',{day:'2-digit',month:'short'}); }
function formatDateTime(value){ if(!value) return ''; const d = new Date(value); return Number.isNaN(d.getTime()) ? value : d.toLocaleString('ru-RU',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}); }
function truncate(value='', n=150){ return value.length>n ? value.slice(0,n).trim()+'…' : value; }

async function api(path, options={}){
  const headers = {...(options.headers||{})};
  if(state.token) headers.Authorization = `Bearer ${state.token}`;
  if(options.body && !(options.body instanceof FormData) && typeof options.body !== 'string'){
    headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, {...options, headers});
  if(response.status === 401 && path !== '/api/login'){
    logout(false); toast('Сессия завершена. Войдите снова.','error'); throw new Error('unauthorized');
  }
  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('application/json') ? await response.json() : await response.text();
  if(!response.ok) throw new Error(data?.detail || data?.message || 'Не удалось выполнить запрос');
  return data;
}

function toast(message, type='success'){
  const el = document.createElement('div'); el.className=`toast ${type}`; el.textContent=message;
  $('#toastRoot').appendChild(el); setTimeout(()=>el.remove(), 3600);
}

function openDialog(id){ const d=document.getElementById(id); if(d && !d.open) d.showModal(); }
function closeDialog(id){ const d=document.getElementById(id); if(d?.open) d.close(); }

function renderDemoAccounts(){
  $('#demoAccounts').innerHTML = demoAccounts.map(a=>`<button type="button" class="demo-account" data-login="${a.login}" data-pass="${a.pass}"><span>${a.initials}</span><b>${a.label}</b><small>${a.login} · ${a.pass}</small></button>`).join('');
  $$('.demo-account').forEach(btn=>btn.addEventListener('click',()=>{
    $('#loginUsername').value=btn.dataset.login; $('#loginPassword').value=btn.dataset.pass;
  }));
}

async function login(username, password){
  const submit=$('#loginForm button[type=submit]'); submit.disabled=true; submit.innerHTML='<span>Входим…</span><span>•••</span>';
  $('#loginError').classList.add('hidden');
  try{
    const data=await api('/api/login',{method:'POST',body:{username,password}});
    state.token=data.token; state.user=data.user; localStorage.setItem('sber_mvp_token',state.token);
    await enterApp();
  }catch(err){ $('#loginError').textContent=err.message; $('#loginError').classList.remove('hidden'); }
  finally{ submit.disabled=false; submit.innerHTML='<span>Войти</span><span>→</span>'; }
}

async function restoreSession(){
  if(!state.token) return false;
  try{ state.user=await api('/api/me'); return true; }catch{ return false; }
}

async function enterApp(){
  $('#loginScreen').classList.add('hidden'); $('#appShell').classList.remove('hidden');
  $('#sidebarAvatar').textContent=state.user.avatar; $('#topAvatar').textContent=state.user.avatar;
  $('#sidebarUserName').textContent=state.user.name; $('#sidebarUserRole').textContent=roleLabels[state.user.role] || state.user.role;
  renderNav();
  state.page = state.user.role==='newcomer' ? 'dashboard' : 'dashboard';
  await navigate(state.page);
}

function logout(show=true){
  state.token=''; state.user=null; state.chat=[]; localStorage.removeItem('sber_mvp_token');
  $('#appShell').classList.add('hidden'); $('#loginScreen').classList.remove('hidden');
  if(show) toast('Вы вышли из сервиса');
}

function allowedNav(item){ return item.roles.includes('all') || item.roles.includes(state.user.role); }
function renderNav(){
  $('#mainNav').innerHTML = navConfig.filter(allowedNav).map(item=>`<button class="nav-item ${item.id===state.page?'active':''}" data-page="${item.id}"><span class="nav-icon">${item.icon}</span><span>${item.label}</span>${item.id==='assistant'?'<span class="nav-badge">AI</span>':''}</button>`).join('');
  $$('.nav-item').forEach(btn=>btn.addEventListener('click',()=>navigate(btn.dataset.page)));
}

async function navigate(page){
  if(!pageNames[page]) page='dashboard';
  state.page=page; renderNav(); $('#pageTitle').textContent=pageNames[page]; $('#breadcrumb').textContent=`${state.user.department} · ${roleLabels[state.user.role]}`;
  $('#content').innerHTML='<div class="skeleton" style="height:220px"></div>';
  closeSidebar();
  try{
    if(page==='dashboard') await renderDashboard();
    if(page==='assistant') await renderAssistant();
    if(page==='knowledge') await renderKnowledge();
    if(page==='onboarding') await renderOnboarding();
    if(page==='meetings') renderMeetings();
    if(page==='documents') renderDocuments();
    if(page==='tasks') await renderTasks();
    if(page==='analytics') await renderAnalytics();
    if(page==='admin') await renderAdmin();
  }catch(err){ $('#content').innerHTML=errorState(err.message); }
}

function pageHead(eyebrow,title,description,actions=''){
  return `<div class="page-head"><div><span class="eyebrow">${escapeHtml(eyebrow)}</span><h1>${escapeHtml(title)}</h1><p>${escapeHtml(description)}</p></div>${actions?`<div class="page-actions">${actions}</div>`:''}</div>`;
}
function errorState(message){ return `<div class="card empty-state"><div class="empty-state-icon">!</div><h3>Не удалось загрузить раздел</h3><p>${escapeHtml(message)}</p><button class="btn btn--primary" onclick="navigate(state.page)">Повторить</button></div>`; }

async function renderDashboard(){
  state.dashboard=await api('/api/dashboard'); const d=state.dashboard; const firstName=state.user.name.split(' ')[0];
  const incomplete=(d.onboarding.items||[]).filter(x=>!x.completed).slice(0,3);
  const taskTotal=Object.values(d.task_counts||{}).reduce((a,b)=>a+b,0);
  const promptChips=d.quick_prompts.map(p=>`<button class="chip" data-prompt="${escapeHtml(p)}">${escapeHtml(p)}</button>`).join('');
  const docs=(d.recent_documents||[]).map(doc=>`<div class="list-row"><span class="list-icon">▤</span><span class="list-copy"><b>${escapeHtml(doc.title)}</b><small>Версия ${escapeHtml(doc.version)} · ${formatDate(doc.updated_at)}</small></span><button class="text-link" data-open-doc="${doc.id}">Открыть</button></div>`).join('') || '<div class="empty-state"><p>Документы пока не добавлены.</p></div>';
  const roleBlock = state.user.role==='newcomer' ? `
    <div class="card card-pad">
      <div class="card-head"><div><h3>План адаптации</h3><p>${d.onboarding.completed} из ${d.onboarding.total} шагов завершено</p></div><button class="text-link" data-nav="onboarding">Весь план</button></div>
      <div class="progress-wrap"><div class="progress-bar" style="width:${d.onboarding.progress}%"></div></div><div class="progress-meta"><span>Прогресс</span><b>${d.onboarding.progress}%</b></div>
      <div class="list" style="margin-top:10px">${incomplete.map(i=>`<div class="list-row"><span class="list-icon">○</span><span class="list-copy"><b>${escapeHtml(i.title)}</b><small>${escapeHtml(i.category)}</small></span></div>`).join('')}</div>
    </div>` : `
    <div class="card card-pad"><div class="card-head"><div><h3>Мои задачи</h3><p>Текущая рабочая очередь</p></div><button class="text-link" data-nav="tasks">Открыть</button></div>
      <div class="grid grid--3"><div><div class="metric-value">${d.task_counts.todo||0}</div><div class="metric-label">К выполнению</div></div><div><div class="metric-value">${d.task_counts.in_progress||0}</div><div class="metric-label">В работе</div></div><div><div class="metric-value">${d.task_counts.done||0}</div><div class="metric-label">Завершено</div></div></div>
    </div>`;
  $('#content').innerHTML=`
    <section class="hero"><div class="hero-inner"><span class="eyebrow eyebrow--light">Персональный помощник</span><h1>${greeting()}, ${escapeHtml(firstName)}</h1><p>${dashboardSubtitle()}</p>
      <form id="heroPrompt" class="hero-prompt"><input name="query" placeholder="Спросите о процессе, документе или рабочей задаче" autocomplete="off"/><button aria-label="Отправить">→</button></form><div class="quick-chips">${promptChips}</div></div></section>
    <div class="grid grid--4" style="margin-top:18px">
      ${metricCard('⌕',d.answers_today,'Ответов сегодня','По базе знаний','green')}
      ${metricCard('◷',`${d.saved_minutes} мин`,'Сэкономлено','Оценка за день','cyan')}
      ${metricCard('✓',taskTotal,'Личных задач','Во всех статусах','yellow')}
      ${metricCard('▤',d.recent_documents.length,'Рекомендовано','Доступно по роли','orange')}
    </div>
    <div class="card card-pad" style="margin-top:18px"><div class="card-head"><div><h3>Быстрые действия</h3><p>Частые сценарии вашей роли</p></div></div><div class="action-grid">${quickActions()}</div></div>
    <div class="grid grid--2" style="margin-top:18px">${roleBlock}<div class="card card-pad"><div class="card-head"><div><h3>Подходящие документы</h3><p>С учётом роли и недавних обновлений</p></div><button class="text-link" data-nav="knowledge">Все документы</button></div><div class="list">${docs}</div></div></div>`;
  bindGlobalActions();
  $('#heroPrompt').addEventListener('submit',e=>{e.preventDefault(); const q=new FormData(e.target).get('query'); if(q) openAssistantWith(q);});
  $$('[data-prompt]').forEach(b=>b.addEventListener('click',()=>openAssistantWith(b.dataset.prompt)));
}
function greeting(){ const h=new Date().getHours(); return h<12?'Доброе утро':h<18?'Добрый день':'Добрый вечер'; }
function dashboardSubtitle(){ return {
  newcomer:'Я помогу пройти адаптацию, найти инструкции и оформить первые доступы.',
  employee:'Найдём нужную информацию, разберём документы и сократим рутинные действия.',
  manager:'Подготовим сводки, выделим риски и превратим договорённости в задачи.',
  expert:'Контролируйте знания, обновляйте инструкции и снижайте поток типовых обращений.',
  developer:'Ищите точную техническую документацию, API и инструкции с проверяемыми источниками.',
  admin:'Управляйте базой знаний, качеством ответов и использованием сервиса.'
}[state.user.role]; }
function metricCard(icon,value,label,sub,color){ return `<div class="card metric-card"><div class="metric-top"><span class="metric-icon ${color}">${icon}</span><span class="metric-delta">активно</span></div><div class="metric-value">${escapeHtml(value)}</div><div class="metric-label"><b>${escapeHtml(label)}</b><br>${escapeHtml(sub)}</div></div>`; }
function quickActions(){
  const common=[
    {icon:'✦',title:'Задать вопрос',sub:'Ответ со ссылками на документы',nav:'assistant'},
    {icon:'◎',title:'Разобрать встречу',sub:'Сводка, решения и задачи',nav:'meetings'},
    {icon:'▧',title:'Проанализировать файл',sub:'PDF, Word, Excel и текст',nav:'documents'},
    {icon:'✓',title:'Создать задачу',sub:'Добавить в личный список',dialog:'taskDialog'}
  ];
  if(state.user.role==='newcomer') common[3]={icon:'◉',title:'Продолжить адаптацию',sub:'Персональный план первых дней',nav:'onboarding'};
  if(['expert','admin'].includes(state.user.role)) common[3]={icon:'⇧',title:'Добавить документ',sub:'Индексировать в базе знаний',dialog:'uploadDialog'};
  return common.map(a=>`<button class="action-card" ${a.nav?`data-nav="${a.nav}"`:`data-open-dialog="${a.dialog}"`}><span class="action-card-icon">${a.icon}</span><b>${a.title}</b><small>${a.sub}</small></button>`).join('');
}

function defaultWelcome(){ return {
  newcomer:'Я уже учёл вашу роль и подразделение. Могу составить план адаптации, найти инструкцию или помочь с заявкой на доступ.',
  employee:'Могу найти регламент, суммаризировать материал, подобрать документы и превратить результат в задачу.',
  manager:'Помогу подготовить краткую сводку, выделить решения и риски, подобрать первичные источники.',
  expert:'Могу проверить базу знаний, найти повторяющиеся темы и подготовить типовой ответ со ссылками.',
  developer:'Ищу по техническим материалам с учётом прав доступа и показываю точные источники.',
  admin:'Могу объяснить метрики сервиса, найти документы и помочь проверить качество базы знаний.'
}[state.user.role]; }
async function renderAssistant(){
  if(!state.chat.length) state.chat=[{type:'assistant',text:defaultWelcome(),sources:[],confidence:1,mode:'system'}];
  const prompts=(state.dashboard?.quick_prompts || dbRolePrompts()).map(p=>`<button class="suggestion-button" data-chat-prompt="${escapeHtml(p)}">${escapeHtml(p)}</button>`).join('');
  $('#content').innerHTML=`<div class="assistant-layout">
    <section class="card chat-panel"><div class="chat-header"><span class="assistant-dot">✦</span><span class="chat-header-copy"><b>СберАссистент</b><small><i class="online"></i>Готов работать · доступ по роли ${escapeHtml(roleLabels[state.user.role])}</small></span><span class="tag">RAG + источники</span></div>
      <div id="chatMessages" class="chat-messages"></div>
      <form id="chatForm" class="chat-compose"><div class="compose-box"><button type="button" class="compose-tool" data-nav="documents" title="Анализ файла">＋</button><textarea id="chatInput" rows="1" placeholder="Напишите вопрос или опишите задачу"></textarea><button class="compose-send" type="submit">↑</button></div><div class="compose-hint"><span>Enter — отправить · Shift+Enter — новая строка</span><span>Ответы требуют проверки первичного источника</span></div></form>
    </section>
    <aside class="assistant-side"><div class="card side-card"><h3>Рекомендуемые запросы</h3><div class="suggestion-list">${prompts}</div></div><div class="card side-card"><h3>Режим ответа</h3><div class="mode-badge"><span>✓</span><div><b>Защищённый RAG</b><small>Поиск только по доступным документам. Генеративный шлюз подключается через конфигурацию.</small></div></div></div><div class="card side-card"><h3>Принципы</h3><div class="list"><div class="list-row"><span class="list-icon">1</span><span class="list-copy"><b>Проверяемые источники</b><small>Ссылка и фрагмент документа</small></span></div><div class="list-row"><span class="list-icon">2</span><span class="list-copy"><b>Ролевой доступ</b><small>Недоступные данные не используются</small></span></div><div class="list-row"><span class="list-icon">3</span><span class="list-copy"><b>Безопасный отказ</b><small>При низкой уверенности — уточнение</small></span></div></div></div></aside>
  </div>`;
  renderChatMessages(); bindGlobalActions();
  $('#chatForm').addEventListener('submit',async e=>{e.preventDefault(); const input=$('#chatInput'); const q=input.value.trim(); if(!q)return; input.value=''; await sendChat(q);});
  $('#chatInput').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();$('#chatForm').requestSubmit();}});
  $$('[data-chat-prompt]').forEach(b=>b.addEventListener('click',()=>sendChat(b.dataset.chatPrompt)));
  const pending=sessionStorage.getItem('pending_prompt'); if(pending){sessionStorage.removeItem('pending_prompt'); setTimeout(()=>sendChat(pending),150);}
}
function dbRolePrompts(){ return state.dashboard?.quick_prompts || ['Найди нужный регламент','Суммаризируй документ','Создай план действий']; }
function renderChatMessages(){
  const box=$('#chatMessages'); if(!box)return;
  box.innerHTML=state.chat.map((m,i)=>{
    const sources=(m.sources||[]).map(s=>`<button class="source-card" data-open-doc="${s.id}"><b>▤ ${escapeHtml(s.title)}</b><small>${escapeHtml(s.excerpt)}</small></button>`).join('');
    const actions=m.type==='assistant'&&i>0?`<div class="message-actions"><button class="message-action" data-feedback="5" data-msg="${m.message_id||''}">Полезно</button><button class="message-action" data-feedback="2" data-msg="${m.message_id||''}">Неточно</button><button class="message-action" data-copy="${i}">Копировать</button></div>`:'';
    const meta=m.type==='assistant'?`<div class="message-meta"><span class="confidence">Уверенность ${Math.round((m.confidence||0)*100)}%</span>${m.latency_ms!==undefined?`<span>${m.latency_ms} мс</span>`:''}<span>${m.mode==='generative-rag'?'Генеративный RAG':'Локальный RAG'}</span></div>`:'';
    return `<div class="message message--${m.type}"><span class="message-avatar">${m.type==='user'?escapeHtml(state.user.avatar):'AI'}</span><div class="message-body"><p>${escapeHtml(m.text).replace(/\n/g,'<br>')}</p>${sources?`<div class="sources">${sources}</div>`:''}${meta}${actions}</div></div>`;
  }).join('');
  bindDocumentLinks();
  $$('[data-feedback]').forEach(b=>b.addEventListener('click',async()=>{try{await api('/api/feedback',{method:'POST',body:{message_id:b.dataset.msg?Number(b.dataset.msg):null,value:Number(b.dataset.feedback)}});toast('Спасибо, оценка сохранена');}catch(e){toast(e.message,'error')}}));
  $$('[data-copy]').forEach(b=>b.addEventListener('click',()=>{navigator.clipboard.writeText(state.chat[Number(b.dataset.copy)].text);toast('Ответ скопирован');}));
  box.scrollTop=box.scrollHeight;
}
async function sendChat(query){
  state.chat.push({type:'user',text:query}); renderChatMessages();
  const box=$('#chatMessages'); const typing=document.createElement('div'); typing.className='message'; typing.id='typing'; typing.innerHTML='<span class="message-avatar">AI</span><div class="message-body"><div class="typing"><i></i><i></i><i></i></div></div>'; box.appendChild(typing); box.scrollTop=box.scrollHeight;
  try{
    const r=await api('/api/chat',{method:'POST',body:{query}}); state.chat.push({type:'assistant',text:r.answer,sources:r.sources,confidence:r.confidence,latency_ms:r.latency_ms,mode:r.mode,message_id:r.message_id});
  }catch(e){ state.chat.push({type:'assistant',text:`Не удалось выполнить запрос: ${e.message}`,sources:[],confidence:0,mode:'error'}); }
  renderChatMessages();
}
function openAssistantWith(prompt){ sessionStorage.setItem('pending_prompt',prompt); navigate('assistant'); }

async function renderKnowledge(query=''){
  state.documents=await api(`/api/knowledge${query?`?query=${encodeURIComponent(query)}`:''}`);
  const canUpload=['expert','admin'].includes(state.user.role);
  $('#content').innerHTML=`${pageHead('Корпоративные знания','База знаний','Документы доступны с учётом вашей роли и области доступа.',canUpload?'<button class="btn btn--primary" data-open-dialog="uploadDialog">＋ Добавить документ</button>':'')}
    <div class="toolbar"><input id="knowledgeSearch" class="filter-input" placeholder="Поиск по названию, тексту или тегам" value="${escapeHtml(query)}"/><div class="filter-group"><button class="filter-btn active">Все</button><button class="filter-btn" data-tag="HR">HR</button><button class="filter-btn" data-tag="доступ">Доступы</button><button class="filter-btn" data-tag="ИБ">ИБ</button><button class="filter-btn" data-tag="API">API</button></div></div>
    <div id="documentGrid" class="document-grid">${documentsHtml(state.documents)}</div>`;
  bindGlobalActions(); bindDocumentLinks();
  let timer; $('#knowledgeSearch').addEventListener('input',e=>{clearTimeout(timer); timer=setTimeout(async()=>{const docs=await api(`/api/knowledge?query=${encodeURIComponent(e.target.value)}`);$('#documentGrid').innerHTML=documentsHtml(docs);bindDocumentLinks();},260)});
  $$('[data-tag]').forEach(b=>b.addEventListener('click',async()=>{ $$('.filter-btn').forEach(x=>x.classList.remove('active'));b.classList.add('active'); const docs=await api(`/api/knowledge?tag=${encodeURIComponent(b.dataset.tag)}`);$('#documentGrid').innerHTML=documentsHtml(docs);bindDocumentLinks(); }));
}
function documentsHtml(docs){
  if(!docs.length) return '<div class="card empty-state" style="grid-column:1/-1"><div class="empty-state-icon">⌕</div><h3>Ничего не найдено</h3><p>Попробуйте изменить формулировку или очистить фильтры.</p></div>';
  return docs.map(d=>`<article class="card document-card"><div class="doc-top"><span class="doc-icon">${docType(d.filename)}</span>${['expert','admin'].includes(state.user.role)?`<button class="doc-menu" data-delete-doc="${d.id}" title="Удалить">×</button>`:'<span class="status active">Доступен</span>'}</div><h3>${escapeHtml(d.title)}</h3><p>${escapeHtml(d.preview||'')}</p><div class="doc-tags">${(d.tags||[]).slice(0,4).map(t=>`<span class="tag">${escapeHtml(t)}</span>`).join('')}</div><div class="doc-footer"><span>v${escapeHtml(d.version)} · ${formatDate(d.updated_at)}</span><button class="text-link" data-open-doc="${d.id}">Открыть</button></div></article>`).join('');
}
function docType(filename=''){ const ext=filename.split('.').pop().toUpperCase(); return ['PDF','DOCX','XLSX','CSV','MD','TXT'].includes(ext)?ext:'DOC'; }
function bindDocumentLinks(){
  $$('[data-open-doc]').forEach(b=>b.addEventListener('click',()=>openDocument(Number(b.dataset.openDoc))));
  $$('[data-delete-doc]').forEach(b=>b.addEventListener('click',async()=>{if(!confirm('Удалить документ из базы знаний?'))return;try{await api(`/api/knowledge/${b.dataset.deleteDoc}`,{method:'DELETE'});toast('Документ удалён');renderKnowledge();}catch(e){toast(e.message,'error')}}));
}
async function openDocument(id){
  try{const d=await api(`/api/knowledge/${id}`); $('#documentDialogContent').innerHTML=`<article class="document-view"><header class="document-view-head"><span class="eyebrow">Документ базы знаний</span><h2>${escapeHtml(d.title)}</h2><div class="document-view-meta"><span class="tag">Версия ${escapeHtml(d.version)}</span><span class="tag">Обновлён ${formatDate(d.updated_at)}</span>${d.tags.map(t=>`<span class="tag">${escapeHtml(t)}</span>`).join('')}</div></header><div class="document-content">${escapeHtml(d.content)}</div></article>`;openDialog('documentDialog');}catch(e){toast(e.message,'error')}
}

async function renderOnboarding(){
  state.onboarding=await api('/api/onboarding'); const o=state.onboarding;
  $('#content').innerHTML=`${pageHead('Первые шаги','Моя адаптация','Персональный маршрут для уверенного старта в команде.')}
  <div class="onboarding-layout"><div class="grid"><section class="card onboarding-hero"><span class="eyebrow">Ваш прогресс</span><h2>${o.completed===o.total?'Адаптация завершена':'Продолжайте в своём темпе'}</h2><p>Ассистент подбирает инструкции и помогает не пропустить обязательные действия. Все пункты можно выполнять в удобном порядке.</p><div class="big-progress"><div class="progress-ring" style="--value:${o.progress}" data-value="${o.progress}"></div><div><b>${o.completed} из ${o.total} шагов</b><p>Следующий рекомендуемый шаг: ${escapeHtml((o.items.find(i=>!i.completed)||o.items[0]).title)}</p></div></div></section><section class="card onboarding-list">${o.items.map(i=>`<div class="onboarding-item"><button class="check-button ${i.completed?'checked':''}" data-toggle-onboarding="${i.id}">${i.completed?'✓':''}</button><div class="onboarding-copy"><b>${escapeHtml(i.title)}</b><p>${escapeHtml(i.description)}</p></div><span class="onboarding-category">${escapeHtml(i.category)}</span></div>`).join('')}</section></div>
  <aside class="grid"><section class="card contact-card"><span class="eyebrow">Ваши контакты</span><div class="contact-person"><span class="avatar">ИП</span><div><b>Ирина Петрова</b><small>Наставник · команда продукта</small></div></div><button class="btn btn--secondary" style="width:100%" data-chat-prompt="Подготовь вопросы для первой встречи с наставником">Подготовить встречу</button></section><section class="card tip-card"><span class="eyebrow eyebrow--light">Совет ассистента</span><h3>Начните с доступов</h3><p>Большинство задержек первой недели связано с неполным набором прав. Я могу подобрать системы для вашей роли и проверить статус заявок.</p><button class="btn btn--ghost" style="color:#fff;border-color:rgba(255,255,255,.2)" data-chat-prompt="Какие доступы нужны новому сотруднику моей роли?">Спросить ассистента</button></section></aside></div>`;
  $$('[data-toggle-onboarding]').forEach(b=>b.addEventListener('click',async()=>{await api(`/api/onboarding/${b.dataset.toggleOnboarding}/toggle`,{method:'POST'});renderOnboarding();}));
  $$('[data-chat-prompt]').forEach(b=>b.addEventListener('click',()=>openAssistantWith(b.dataset.chatPrompt)));
}

async function renderTasks(){
  state.tasks=await api('/api/tasks');
  const cols=[['todo','К выполнению'],['in_progress','В работе'],['done','Завершено']];
  $('#content').innerHTML=`${pageHead('Личная продуктивность','Мои задачи','Задачи из встреч, ответов ассистента и ручного ввода.','<button class="btn btn--primary" data-open-dialog="taskDialog">＋ Новая задача</button>')}<div class="task-board">${cols.map(([status,label])=>{const items=state.tasks.filter(t=>t.status===status);return `<section class="task-column"><div class="task-column-head"><h3>${label}</h3><span>${items.length}</span></div>${items.length?items.map(taskCard).join(''):'<div class="empty-state" style="padding:25px 10px"><p>Здесь пока пусто</p></div>'}</section>`}).join('')}</div>`;
  bindGlobalActions();
  $$('[data-move-task]').forEach(b=>b.addEventListener('click',async()=>{await api(`/api/tasks/${b.dataset.moveTask}`,{method:'PATCH',body:{status:b.dataset.status}});renderTasks();}));
}
function taskCard(t){ const next=t.status==='todo'?'in_progress':t.status==='in_progress'?'done':'todo'; const nextLabel=t.status==='todo'?'Начать':t.status==='in_progress'?'Завершить':'Вернуть';return `<article class="task-card"><h4>${escapeHtml(t.title)}</h4>${t.description?`<p>${escapeHtml(truncate(t.description,130))}</p>`:''}<div class="task-card-footer"><span class="tag"><i class="priority-dot ${t.priority}"></i>${t.due_date?formatDate(t.due_date):t.source}</span><button class="task-move" data-move-task="${t.id}" data-status="${next}">${nextLabel} →</button></div></article>`; }

function renderMeetings(){
  $('#content').innerHTML=`${pageHead('Автоматизация встреч','Суммаризация встречи','Вставьте расшифровку — ассистент выделит итоги, решения, риски и задачи.')}
  <div class="split-workspace"><section class="card workspace-card"><h3>Расшифровка или заметки</h3><p>Можно вставить текст из SberJazz, протокол или собственные заметки.</p><textarea id="meetingText" class="large-textarea" placeholder="Пример: Обсудили запуск пилота. Решили начать с подразделения продаж. Анна подготовит список документов до 15.08. Алексей проверит доступ к API. Риск — задержка согласования ИБ..."></textarea><div class="workspace-actions"><label class="toggle-line"><input id="meetingCreateTasks" type="checkbox" checked/> Создать найденные задачи в моём списке</label><button id="summarizeMeeting" class="btn btn--primary">✦ Суммаризировать</button></div></section><section id="meetingResult" class="card workspace-card"><div class="result-placeholder"><div><span>◎</span><h3>Результат появится здесь</h3><p>Краткое содержание, решения, риски и задачи.</p></div></div></section></div>`;
  $('#summarizeMeeting').addEventListener('click',summarizeMeeting);
}
async function summarizeMeeting(){
  const text=$('#meetingText').value.trim(); if(text.length<10){toast('Добавьте текст встречи','error');return}
  const btn=$('#summarizeMeeting');btn.disabled=true;btn.textContent='Анализируем…';
  try{const r=await api('/api/meetings/summarize',{method:'POST',body:{transcript:text,create_tasks:$('#meetingCreateTasks').checked}});$('#meetingResult').innerHTML=`<h3>Результат встречи</h3><p>Структурировано на основе текста.</p><div class="result-block"><h4>Краткое содержание</h4><p>${escapeHtml(r.summary)}</p></div><div class="result-block"><h4>Решения</h4><ul>${r.decisions.map(x=>`<li>${escapeHtml(x)}</li>`).join('')}</ul></div>${r.risks?.length?`<div class="result-block"><h4>Риски</h4><ul>${r.risks.map(x=>`<li>${escapeHtml(x)}</li>`).join('')}</ul></div>`:''}<div class="result-block"><h4>Задачи ${r.created_tasks.length?`· создано ${r.created_tasks.length}`:''}</h4>${r.tasks.length?`<ul>${r.tasks.map(x=>`<li>${escapeHtml(x.title)}${x.due_date?` · до ${escapeHtml(x.due_date)}`:''}</li>`).join('')}</ul>`:'<p>Явные задачи не обнаружены.</p>'}</div>`;if(r.created_tasks.length)toast(`Создано задач: ${r.created_tasks.length}`);}catch(e){toast(e.message,'error')}finally{btn.disabled=false;btn.textContent='✦ Суммаризировать'}
}

function renderDocuments(){
  $('#content').innerHTML=`${pageHead('Работа с файлами','Анализ документов','Загрузите файл — сервис извлечёт текст, подготовит сводку и подберёт связанные материалы.')}
  <div class="split-workspace"><section class="card workspace-card"><label id="analysisDrop" class="upload-zone"><input id="analysisFile" type="file" accept=".pdf,.docx,.xlsx,.csv,.txt,.md"/><span class="upload-zone-icon">⇧</span><h3>Перетащите файл сюда</h3><p>PDF, DOCX, XLSX, CSV, TXT или MD · до 12 МБ</p><span class="btn btn--secondary">Выбрать файл</span></label><div id="selectedFile" class="list" style="margin-top:14px"></div><button id="analyzeFileButton" class="btn btn--primary" style="width:100%;margin-top:12px" disabled>✦ Проанализировать</button></section><section id="analysisResult" class="card workspace-card"><div class="result-placeholder"><div><span>▧</span><h3>Здесь появится анализ</h3><p>Сводка, ключевые темы, числа и связанные документы.</p></div></div></section></div>`;
  const input=$('#analysisFile'), drop=$('#analysisDrop'), btn=$('#analyzeFileButton');
  input.addEventListener('change',()=>selectAnalysisFile(input.files[0]));
  ['dragenter','dragover'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.add('dragging')}));
  ['dragleave','drop'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove('dragging')}));
  drop.addEventListener('drop',e=>{if(e.dataTransfer.files[0]){input.files=e.dataTransfer.files;selectAnalysisFile(e.dataTransfer.files[0])}});
  btn.addEventListener('click',()=>analyzeFile(input.files[0]));
}
function selectAnalysisFile(file){if(!file)return;$('#selectedFile').innerHTML=`<div class="list-row"><span class="list-icon">${docType(file.name)}</span><span class="list-copy"><b>${escapeHtml(file.name)}</b><small>${(file.size/1024).toFixed(1)} КБ</small></span><span class="status active">Готов</span></div>`;$('#analyzeFileButton').disabled=false;}
async function analyzeFile(file){if(!file)return;const btn=$('#analyzeFileButton');btn.disabled=true;btn.textContent='Извлекаем и анализируем…';const fd=new FormData();fd.append('file',file);try{const r=await api('/api/documents/analyze',{method:'POST',body:fd});$('#analysisResult').innerHTML=`<h3>Анализ файла</h3><p>${escapeHtml(r.filename)} · ${r.paragraphs} блоков · ${r.characters.toLocaleString('ru-RU')} знаков</p><div class="result-block"><h4>Краткое содержание</h4><p class="analysis-summary">${escapeHtml(r.summary)}</p></div><div class="result-block"><h4>Ключевые темы</h4><div class="keyword-cloud">${r.keywords.map(k=>`<span class="keyword">${escapeHtml(k)}</span>`).join('')}</div></div>${r.facts.length?`<div class="result-block"><h4>Числа и показатели</h4><div class="keyword-cloud">${r.facts.map(k=>`<span class="tag">${escapeHtml(k)}</span>`).join('')}</div></div>`:''}<div class="result-block"><h4>Связанные документы</h4>${r.related_documents.length?r.related_documents.map(s=>`<button class="source-card" data-open-doc="${s.id}"><b>${escapeHtml(s.title)}</b><small>${escapeHtml(s.excerpt)}</small></button>`).join(''):'<p>Подходящие материалы не найдены.</p>'}</div>`;bindDocumentLinks();}catch(e){toast(e.message,'error')}finally{btn.disabled=false;btn.textContent='✦ Проанализировать'} }

async function renderAnalytics(){
  const m=await api('/api/admin/metrics'); state.admin=m; const max=Math.max(...m.daily.map(x=>x.c),1);
  $('#content').innerHTML=`${pageHead('Контроль эффекта','Аналитика использования','Показатели демонстрационного контура и качество ответов.')}
    <div class="grid grid--4">${metricCard('⌕',m.queries,'Запросов','За всё время','green')}${metricCard('◎',`${Math.round(m.avg_confidence*100)}%`,'Уверенность','Среднее значение','cyan')}${metricCard('◷',`${m.avg_latency_ms} мс`,'Задержка','Средний ответ','yellow')}${metricCard('★',m.csat,'CSAT','Оценка пользователей','orange')}</div>
    <div class="grid grid--2" style="margin-top:18px"><section class="card card-pad"><div class="card-head"><div><h3>Динамика запросов</h3><p>Последние дни активности</p></div></div><div class="chart-bars">${m.daily.length?m.daily.map(x=>`<div class="bar-wrap"><div class="bar" style="height:${Math.max(6,x.c/max*100)}%" title="${x.c}"></div><span class="bar-label">${x.day.slice(5)}</span></div>`).join(''):'<div class="empty-state"><p>Данные появятся после запросов.</p></div>'}</div></section><section class="card card-pad"><div class="card-head"><div><h3>Контур MVP</h3><p>Текущее состояние данных</p></div></div><table class="metric-table"><tr><th>Показатель</th><th>Значение</th></tr><tr><td>Пользователи</td><td>${m.users}</td></tr><tr><td>Документы</td><td>${m.documents}</td></tr><tr><td>Ролевых сегментов</td><td>${m.roles.length}</td></tr><tr><td>Ответов со ссылками</td><td>${m.queries?'100%':'—'}</td></tr></table></section></div>
    <section class="card card-pad" style="margin-top:18px"><div class="card-head"><div><h3>Запросы с низкой уверенностью</h3><p>Кандидаты на уточнение базы знаний</p></div></div>${m.low_confidence.length?`<table class="metric-table"><tr><th>Запрос</th><th>Уверенность</th><th>Дата</th></tr>${m.low_confidence.map(x=>`<tr><td>${escapeHtml(x.query)}</td><td>${Math.round(x.confidence*100)}%</td><td>${formatDateTime(x.created_at)}</td></tr>`).join('')}</table>`:'<div class="empty-state"><p>Пока нет запросов с низкой уверенностью.</p></div>'}</section>`;
}

async function renderAdmin(){
  const [m,audit]=await Promise.all([api('/api/admin/metrics'),api('/api/admin/audit')]);
  $('#content').innerHTML=`${pageHead('Администрирование','Управление сервисом','База знаний, аудит действий и контроль безопасного контура.','<button class="btn btn--primary" data-open-dialog="uploadDialog">⇧ Добавить документ</button>')}
    <div class="grid grid--3">${metricCard('♙',m.users,'Пользователей','Демо-роли','green')}${metricCard('▤',m.documents,'Документов','В активном индексе','cyan')}${metricCard('⌕',m.queries,'Запросов','Журнал взаимодействий','yellow')}</div>
    <div class="grid grid--2" style="margin-top:18px"><section class="card card-pad"><div class="card-head"><div><h3>Быстрые настройки</h3><p>Основные административные действия</p></div></div><div class="action-grid" style="grid-template-columns:repeat(2,1fr)"><button class="action-card" data-open-dialog="uploadDialog"><span class="action-card-icon">⇧</span><b>Загрузить документ</b><small>Добавить материал и права доступа</small></button><button class="action-card" data-nav="knowledge"><span class="action-card-icon">▤</span><b>Проверить базу</b><small>Версии, теги и доступность</small></button><button class="action-card" data-nav="analytics"><span class="action-card-icon">▥</span><b>Открыть метрики</b><small>Качество и использование</small></button><button class="action-card" data-chat-prompt="Какие документы базы знаний требуют обновления?"><span class="action-card-icon">✦</span><b>Проверить актуальность</b><small>Запрос к ассистенту</small></button></div></section><section class="card card-pad"><div class="card-head"><div><h3>Журнал аудита</h3><p>Последние действия пользователей</p></div></div><div class="audit-list">${audit.map(x=>`<div class="audit-item"><span class="audit-dot"></span><div><b>${escapeHtml(x.name||'Система')} · ${escapeHtml(x.action)} ${escapeHtml(x.object_type)}</b><p>${escapeHtml(x.details||x.object_id||'')}</p></div><time>${formatDateTime(x.created_at)}</time></div>`).join('')}</div></section></div>`;
  bindGlobalActions(); $$('[data-chat-prompt]').forEach(b=>b.addEventListener('click',()=>openAssistantWith(b.dataset.chatPrompt)));
}

function bindGlobalActions(){
  $$('[data-nav]').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.nav)));
  $$('[data-open-dialog]').forEach(b=>b.addEventListener('click',()=>openDialog(b.dataset.openDialog)));
  bindDocumentLinks();
}
function openSidebar(){ $('#sidebar').classList.add('open'); $('#sidebarBackdrop').classList.add('show'); }
function closeSidebar(){ $('#sidebar').classList.remove('open'); $('#sidebarBackdrop').classList.remove('show'); }

function initEvents(){
  renderDemoAccounts();
  $('#loginForm').addEventListener('submit',e=>{e.preventDefault();login($('#loginUsername').value,$('#loginPassword').value)});
  $('#togglePassword').addEventListener('click',()=>{const i=$('#loginPassword');i.type=i.type==='password'?'text':'password'});
  $('#logoutButton').addEventListener('click',()=>logout()); $('#menuButton').addEventListener('click',openSidebar); $('#sidebarClose').addEventListener('click',closeSidebar); $('#sidebarBackdrop').addEventListener('click',closeSidebar);
  $('#helpButton').addEventListener('click',()=>openDialog('aboutDialog'));
  $$('[data-close-dialog]').forEach(b=>b.addEventListener('click',()=>closeDialog(b.dataset.closeDialog)));
  $$('dialog').forEach(d=>d.addEventListener('click',e=>{if(e.target===d)d.close()}));
  $('#uploadForm').addEventListener('submit',async e=>{e.preventDefault();const btn=e.target.querySelector('[type=submit]');btn.disabled=true;btn.textContent='Индексируем…';try{const fd=new FormData(e.target);const r=await api('/api/knowledge/upload',{method:'POST',body:fd});toast(`Документ добавлен · ${r.chunks} фрагментов`);e.target.reset();closeDialog('uploadDialog');if(state.page==='knowledge')renderKnowledge();}catch(err){toast(err.message,'error')}finally{btn.disabled=false;btn.textContent='Загрузить и индексировать'}});
  $('#taskForm').addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(e.target);try{await api('/api/tasks',{method:'POST',body:Object.fromEntries(f.entries())});toast('Задача создана');e.target.reset();closeDialog('taskDialog');if(state.page==='tasks')renderTasks();}catch(err){toast(err.message,'error')}});
  document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();navigate('assistant')}if(e.key==='Escape')closeSidebar()});
  document.addEventListener('click',e=>{const nav=e.target.closest('[data-nav]');if(nav&&!nav.closest('#content')&&!nav.closest('#mainNav')) navigate(nav.dataset.nav)});
}

(async function init(){
  initEvents();
  if(await restoreSession()) await enterApp();
  else { state.token=''; localStorage.removeItem('sber_mvp_token'); }
})();
